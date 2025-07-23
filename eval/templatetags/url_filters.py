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

@register.filter
def get_index(lst, idx):
    """Return the item at index idx from the list lst."""
    try:
        return lst[idx]
    except (IndexError, TypeError):
        return ""

@register.filter
def get_field_value(obj, field_name):
    """Get field value using the TrainerTask's get_field_value method"""
    if hasattr(obj, 'get_field_value'):
        return obj.get_field_value(field_name)
    return getattr(obj, field_name, '')
