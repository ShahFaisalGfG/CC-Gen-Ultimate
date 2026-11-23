# options.py - route serving option lists that populate UI dropdowns

from fastapi import APIRouter

from ccgen.config.options import option_lists

router = APIRouter()


@router.get("/options")
def get_options() -> dict[str, list]:
    """Return every option list needed to populate the task settings UI (the same as `ccgen options`)."""
    return option_lists()
