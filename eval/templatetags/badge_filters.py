# eval/templatetags/badge_filters.py

import random
from django import template

register = template.Library()

BADGE_COLOR_CLASSES = [
    "bg-purple-50 border border-purple-200 text-purple-800",
    "bg-blue-50 border border-blue-200 text-blue-800",
    "bg-emerald-50 border border-emerald-200 text-emerald-800",
    "bg-amber-50 border border-amber-200 text-amber-800",
    "bg-orange-50 border border-orange-200 text-orange-800",
    "bg-pink-50 border border-pink-200 text-pink-800",
    "bg-green-50 border border-green-200 text-green-800",
    "bg-red-50 border border-red-200 text-red-800",
    "bg-yellow-50 border border-yellow-200 text-yellow-800",
]

@register.filter
def random_badge_class(value):
    return random.choice(BADGE_COLOR_CLASSES)
