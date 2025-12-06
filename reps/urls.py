"""
URL patterns for the reps app.
"""

from django.urls import path
from . import views

app_name = 'reps'

urlpatterns = [
    path('lookup/', views.lookup_reps, name='lookup'),
]
