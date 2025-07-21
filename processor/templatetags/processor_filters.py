from django import template

register = template.Library()

@register.filter
def group_title(title):
    """Extract the group name from the step title."""
    if not title:
        return ''
    # Remove any '#' numbers and split by '-', take first part
    return title.split('#')[0].split('-')[0].strip()

@register.filter
def count_completed(step_list):
    """Count items with status 'Completed' in the list."""
    return sum(1 for step in step_list if step.get('status') == 'Completed')

@register.filter
def count_completed_percent(step_list):
    """Calculate the percentage of completed steps."""
    if not step_list:
        return 0
    completed = sum(1 for step in step_list if step.get('status') == 'Completed')
    return int((completed / len(step_list)) * 100)
