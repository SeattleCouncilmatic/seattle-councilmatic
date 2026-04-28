"""
URL patterns for the reps app.
"""

from django.urls import path
from . import views

app_name = 'reps'

urlpatterns = [
    path('lookup/', views.lookup_reps, name='lookup'),
    path('', views.reps_index, name='index'),
    path('districts/<str:number>/', views.district_detail, name='district_detail'),
    path('<slug:slug>/', views.rep_detail, name='detail'),
]
