from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('project/analyze/', views.create_project_scan, name='create_project_scan'),
    path('scan/<int:scan_id>/download/<str:artifact>/', views.scan_download, name='scan_download'),
    path('scan/<int:scan_id>/', views.scan_detail, name='scan_detail'),
    path('proposal/<int:proposal_id>/edit/', views.edit_proposal, name='edit_proposal'),
    path('proposal/<int:proposal_id>/<str:action>/', views.proposal_action, name='proposal_action'),
    path('scan/<int:scan_id>/export/<str:format>/', views.export_report, name='export_report'),
]
