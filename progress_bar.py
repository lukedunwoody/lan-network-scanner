import time

FILLED_ICON = "█" # ▋ for fonts with long regular block
EMPTY_ICON = "·"
BAR_LENGTH = 50

def map_value(n, start1, stop1, start2, stop2, within_bounds=False):
    mapped = (n - start1) / (stop1 - start1) * (stop2 - start2) + start2
    if within_bounds:
        low, high = sorted((start2, stop2))
        return max(min(mapped, high), low)
    return mapped

def generate_bar(filled):
    lowest_color = 20
    r = int(map_value(filled, 0.5, 1, 200, lowest_color, True))
    g = int(map_value(filled, 0, 0.5, lowest_color, 150, True))
    b = lowest_color

    filled_length = round(filled * BAR_LENGTH)

    return f"\033[38;2;{r};{g};{b}m{FILLED_ICON}\033[0m" * filled_length + EMPTY_ICON * (BAR_LENGTH - filled_length)

def generate_percent_str(filled):
    percent = round(filled*100)
    return f"{f"{percent}%":<3}"

def prepare(total, message=None):
    percent_str = generate_percent_str(0)
    bar = generate_bar(0)

    print(f"{percent_str} [{bar}] No activity yet")
    print(f"{message} 0/{total}")

def update(current, total, last_time, message=None):
    print("\033[2A\033[J", end="")

    filled = current/total
    percent_str = generate_percent_str(filled)
    bar = generate_bar(filled)

    elapsed = time.time() - last_time
    elapsed_ms = round(elapsed*1000)

    print(f"{percent_str} [{bar}] {elapsed_ms}ms since last")
    print(f"{message} {current}/{total}")

def finish(total, start_time, message=None):
    print("\033[2A\033[J", end="")

    percent_str = generate_percent_str(1)
    bar = generate_bar(1)

    total_elapsed = round(time.time() - start_time, 2)

    print(f"{percent_str} [{bar}] {total_elapsed}s in total")
    print(f"\033[38;2;0;150;0m{message} finished {total}/{total}\033[0m")
