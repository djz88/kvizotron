"""A name shown with a pencil that turns it into a field (AC-160).

One component for every name the administration lets one change on the spot. With HTMX the
display and the field are swapped as partials; without it the pencil is a link to the same page
with the field open and a refusal is that page with status 400. The place that uses it gives the
routes, the saving is the place's own.
"""

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.utils import translation


@dataclass
class NameField:
    label: str  # what the field is called ("Bank name")
    field: str  # the name of the form field and of the `?edit=` value
    key: str  # id of the object, so that a page with several names has unique ids
    value: str
    save_url: str  # POST: save
    edit_url: str  # GET: the field as a partial
    view_url: str  # GET: the display as a partial
    edit_page: str  # the host page with the field open (no JavaScript)
    back_page: str  # the host page with the field closed (no JavaScript)
    max_length: int
    editing: bool = False
    error: str = ""
    note: str = ""
    saved: bool = False
    placeholder: str = ""  # shown, in emphasis, instead of an empty name
    bare: bool = False  # only the pencil, the name is shown elsewhere (a summary)
    mirror: str = ""  # id of an element that shows the same name; a save swaps its text too
    link: str = ""  # the name is a link to this address (a folder in a list)
    tag: str = "span"  # the element of the shown name; a heading gets a block wrapper
    hidden: dict[str, str] = dataclass_field(default_factory=dict)  # extra hidden inputs
    suffix: str = ""  # a fixed part after the value, in the link and beside the field (an address)
    pencil_label: str = ""  # the pencil's own label; empty: "Edit name"
    required: bool = True  # False: an empty value is allowed (it means a default)


def wants_partial(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request") == "true"


def render_field(request: HttpRequest, field: NameField, status: int = 200) -> HttpResponse:
    """The display or the field of one name, drawn alone."""
    translation.activate(request.locale)  # type: ignore[attr-defined]
    html = render_to_string("admin/_inline_name_field.html", {"field": field}, request)
    return HttpResponse(html, status=status)
