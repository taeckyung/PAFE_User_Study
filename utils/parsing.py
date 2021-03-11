from urlvalidator import URLValidator, ValidationError
import pafy


def get_best_url(path: str) -> str:
    validate = URLValidator()
    try:
        validate(path)
        video = pafy.new(path)
        best = video.getbest()
        return best.url

    except ValidationError:
        return path
