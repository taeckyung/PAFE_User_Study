import playsound


def play(url: str):
    """
    Try to execute sound file asynchronously as possible.
    Windows use winsound module since playsound module sometimes make EncodingError.

    :param url:
    :return:
    """
    try:
        playsound.playsound(url, False)
    except Exception as e:
        print(e)
        try:
            playsound.playsound(url, True)
        except Exception as e:
            print(e)
