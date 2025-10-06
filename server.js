import express from 'express';
import { Readable } from 'stream';
import Busboy from 'busboy';
import fs from 'fs/promises';
import { createWriteStream, createReadStream } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import http from 'http';

const app = express();
const PORT = 3000;
const OLLAMA_BASE_URL = 'http://127.0.0.1:8000';

let modelsConfig = { cheap_text: {}, vision: {} };

try {
  const configData = await fs.readFile('models.json', 'utf-8');
  modelsConfig = JSON.parse(configData);
  console.log('✅ Loaded models.json configuration');
} catch (err) {
  console.warn('⚠️  models.json not found, using defaults');
  modelsConfig = {
    cheap_text: { model: 'llava:latest', options: { num_ctx: 1024, batch_size: 256 } },
    vision: { model: 'llava:latest', options: { num_ctx: 2048, batch_size: 256 } }
  };
}

app.use((req, res, next) => {
  const origin = req.headers.origin || '';
  if (origin.includes('localhost') || origin.includes('127.0.0.1') || origin.includes('replit')) {
    res.header('Access-Control-Allow-Origin', origin);
    res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  }
  if (req.method === 'OPTIONS') {
    return res.sendStatus(200);
  }
  next();
});

app.get('/health', async (req, res) => {
  try {
    const response = await fetch(`${OLLAMA_BASE_URL}/api/tags`, {
      signal: AbortSignal.timeout(5000)
    });
    if (response.ok) {
      const data = await response.json();
      res.json({ status: 'ok', ollama: 'ready', models: data.models?.length || 0 });
    } else {
      res.status(503).json({ status: 'error', message: 'Ollama not responding' });
    }
  } catch (err) {
    res.status(503).json({ status: 'error', message: err.message });
  }
});

function parseMultipart(req) {
  return new Promise((resolve, reject) => {
    const busboy = Busboy({ 
      headers: req.headers,
      limits: { fileSize: 10 * 1024 * 1024 }
    });
    
    const result = { prompt: '', images: [] };
    const tempFiles = [];

    busboy.on('field', (fieldname, val) => {
      if (fieldname === 'prompt' || fieldname === 'model' || fieldname === 'stream') {
        result[fieldname] = val;
      }
    });

    busboy.on('file', (fieldname, file, info) => {
      if (fieldname === 'image') {
        const tempPath = join(tmpdir(), `upload-${Date.now()}-${info.filename}`);
        tempFiles.push(tempPath);
        
        const writeStream = createWriteStream(tempPath);
        file.pipe(writeStream);
        
        writeStream.on('finish', async () => {
          try {
            const buffer = await fs.readFile(tempPath);
            const base64 = buffer.toString('base64');
            const mimeType = info.mimeType || 'image/jpeg';
            result.images.push(`data:${mimeType};base64,${base64}`);
            await fs.unlink(tempPath);
          } catch (err) {
            console.error('Error processing image:', err);
          }
        });
      } else {
        file.resume();
      }
    });

    busboy.on('finish', () => {
      setTimeout(() => resolve(result), 100);
    });

    busboy.on('error', reject);
    req.pipe(busboy);
  });
}

app.post('/generate', async (req, res) => {
  let payload;

  try {
    if (req.headers['content-type']?.includes('multipart/form-data')) {
      payload = await parseMultipart(req);
    } else {
      const chunks = [];
      for await (const chunk of req) {
        chunks.push(chunk);
      }
      payload = JSON.parse(Buffer.concat(chunks).toString());
    }

    if (!payload.model) {
      if (payload.images && payload.images.length > 0) {
        payload.model = modelsConfig.vision.model;
        payload.options = { ...modelsConfig.vision.options, ...payload.options };
        console.log(`🎨 Using vision model: ${payload.model}`);
      } else {
        payload.model = modelsConfig.cheap_text.model;
        payload.options = { ...modelsConfig.cheap_text.options, ...payload.options };
        console.log(`📝 Using cheap_text model: ${payload.model}`);
      }
    }

    if (payload.stream === undefined || payload.stream === 'true') {
      payload.stream = true;
    }

    console.log(`🚀 Generating with model: ${payload.model}, stream: ${payload.stream}`);

    const controller = new AbortController();
    req.on('close', () => {
      controller.abort();
      console.log('⚠️  Client disconnected, aborting request');
    });

    const response = await fetch(`${OLLAMA_BASE_URL}/api/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
      keepalive: true
    });

    if (!response.ok) {
      const error = await response.text();
      return res.status(response.status).json({ error });
    }

    res.setHeader('Content-Type', 'application/x-ndjson');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');

    if (payload.stream) {
      for await (const chunk of response.body) {
        res.write(chunk);
      }
      res.end();
    } else {
      const data = await response.json();
      res.json(data);
    }

  } catch (err) {
    console.error('❌ Error in /generate:', err.message);
    if (!res.headersSent) {
      res.status(500).json({ error: err.message });
    }
  }
});

const server = http.createServer(app);

server.keepAliveTimeout = 610000;
server.headersTimeout = 620000;
server.timeout = 0;

server.listen(PORT, '0.0.0.0', () => {
  console.log(`✅ Proxy server listening on http://0.0.0.0:${PORT}`);
  console.log(`📡 Forwarding to Ollama at ${OLLAMA_BASE_URL}`);
  console.log(`🔧 Timeouts: keepAlive=${server.keepAliveTimeout}ms, headers=${server.headersTimeout}ms`);
});
