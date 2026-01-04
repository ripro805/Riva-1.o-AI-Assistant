import random

confused = [
    "I didn't quite get that.",
    "Can you say that a bit more simply?",
    "My brain is buffering right now."
]

greetings = [
    "Hello boss 😎",
    "Yes? I am online.",
    "Ready to work!"
]

def random_reply(list_name):
    return random.choice(list_name)
