from django import template

from documents.refs import linkify_internal_refs

register = template.Library()


@register.filter
def linkify_refs(text, anchors):
    """Шаблонный фильтр: текст статьи → safe HTML с внутренними гиперссылками."""
    return linkify_internal_refs(text, anchors)
