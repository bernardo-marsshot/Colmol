
from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('upload/', views.upload_inbound, name='upload_inbound'),
    path('inbound/<int:pk>/', views.inbound_detail, name='inbound_detail'),
    path('inbound/<int:pk>/excel/', views.export_excel, name='export_excel'),
    path('po/', views.po_list, name='po_list'),
]
