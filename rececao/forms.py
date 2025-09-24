
from django import forms
from .models import InboundDocument

class InboundUploadForm(forms.ModelForm):
    class Meta:
        model = InboundDocument
        fields = ['supplier','doc_type','number','file']
