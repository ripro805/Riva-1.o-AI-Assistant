import datetime

def get_mood():
    hour = datetime.datetime.now().hour

    if hour < 10:
        return "happy"
    elif hour < 18:
        return "work"
    else:
        return "sleepy"
