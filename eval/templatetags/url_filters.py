from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key, "")

@register.filter
def split(value, delimiter=","):
    if not value:
        return []
    return [v.strip() for v in value.split(delimiter)]

@register.filter
def trim(value):
    if isinstance(value, str):
        return value.strip()
    return value

@register.filter
def attr(obj, name):
    return getattr(obj, name, "")
