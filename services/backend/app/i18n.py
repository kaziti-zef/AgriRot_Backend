"""Messages en anglais pour Accept-Language: en (contrat §1 : « les champs message sont traduits »).
Le français est la langue par défaut (message d'origine). Les phrases d'explication produites par le
moteur restent en français (voir README : point ouvert)."""
from starlette.requests import Request

EN = {
    "INVALID_REQUEST": "The request is malformed.",
    "INVALID_POLYGON": "The drawn polygon self-intersects, has fewer than 3 vertices, or has a null or out-of-range area.",
    "INVALID_CREDENTIALS": "Incorrect identifier or password.",
    "TOKEN_EXPIRED": "Your session has expired. Please sign in again.",
    "TOKEN_INVALID": "Missing or invalid access token.",
    "FORBIDDEN_ROLE": "Your role does not allow this action.",
    "NOT_FARM_MEMBER": "You do not have access to this farm.",
    "FARM_NOT_FOUND": "Farm not found.",
    "PARCEL_NOT_FOUND": "Parcel not found.",
    "USER_NOT_FOUND": "No account matches this identifier. You can send an invitation.",
    "MEMBER_NOT_FOUND": "Member not found.",
    "STRATEGY_NOT_FOUND": "Strategy not found or expired. Run the calculation again.",
    "CROP_NOT_FOUND": "Unknown crop for this region.",
    "REGION_NOT_SUPPORTED": "This region is not supported yet.",
    "ACCOUNT_ALREADY_EXISTS": "An account already exists with this identifier.",
    "MEMBER_ALREADY_EXISTS": "This person is already a member of the farm.",
    "LAST_OWNER": "The owner cannot be removed. Transfer ownership first.",
    "PARCEL_OVERLAP": "This parcel overlaps an existing parcel of the farm.",
    "PARCEL_NAME_TAKEN": "A parcel already has this name in the farm.",
    "VERSION_CONFLICT": "This data was changed by someone else. Reload before editing.",
    "PRECONDITION_FAILED": "Required information is missing before the calculation.",
    "VALIDATION_ERROR": "Some values are invalid.",
    "EXCLUDED_CROP": "This crop is excluded for this parcel.",
    "NO_CROP_AVAILABLE": "Too many crops excluded: at least two must remain available.",
    "NO_SUITABLE_CROP": "No crop is suitable enough for the parcel's conditions.",
    "INVALID_SCENARIO": "Simulation values are outside the allowed range.",
    "TOO_MANY_REQUESTS": "Too many attempts. Try again in a few minutes.",
    "INTERNAL_ERROR": "An error occurred. Share the request code if the problem persists.",
    "CLIMATE_DATA_UNAVAILABLE": "Climate data is temporarily unavailable.",
    "ENGINE_UNAVAILABLE": "Strategy calculation is temporarily unavailable.",
    "PDF_GENERATION_FAILED": "The PDF could not be generated. Use the browser's print function.",
    "NOT_FOUND": "Resource not found.",
}

AVERTISSEMENTS_EN = {
    "EXCLUSION_TOO_RESTRICTIVE": "Almost all crops are excluded; rotation rules may be compromised.",
    "CONSTRAINTS_RELAXED": "No rotation met every rule: secondary rules were relaxed.",
    "LOW_CONFIDENCE": "Low confidence: several default values were used.",
    "SRTM_UNAVAILABLE": "Elevation and slope unavailable; enter the slope manually.",
    "OUTSIDE_COVERED_REGION": "Parcel outside the pilot area: local SMAP, NDVI and SRTM are unavailable.",
    "CENTROID_MOVED": "The parcel centre moved by more than 5 km: check the climate diagnosis.",
    "MARKETS_NOT_PROVIDED": "No market outlet provided: the income criterion is estimated without your markets.",
    "EXCLUDED_CROP_IN_HISTORY": "An excluded crop appears in the history.",
    "CROP_COLLAPSE": "A crop is no longer suited to the simulated climate.",
    "SYNTHETIC_CLIMATE": "Synthetic climate series (test data): results do not apply to a real parcel.",
}

DISCLAIMER_EN = ("Decision-support tool: these estimates support your judgement and do not replace the advice of a "
                 "local agronomist.")


def langue(request: Request | None) -> str:
    h = (request.headers.get("accept-language", "") if request else "").strip().lower()
    return "en" if h.startswith("en") else "fr"


def message(code: str, defaut: str, lang: str) -> str:
    return EN.get(code, defaut) if lang == "en" else defaut


def avertissements(ws: list[dict], lang: str) -> list[dict]:
    if lang != "en":
        return ws
    return [{**w, "message": AVERTISSEMENTS_EN.get(w.get("code"), w.get("message"))} for w in ws]
