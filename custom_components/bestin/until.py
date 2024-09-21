import re

def check_ip_or_serial(id: str) -> bool:
    """
    Verify that the string is an IP address or serial device path.
    """
    ip_pattern = re.compile(r"^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$")
    serial_pattern = re.compile(r"/dev/tty(USB|AMA)\d+")

    if ip_pattern.match(id) or serial_pattern.match(id):
        return True
    else:
        return False

def formatted_name(name: str) -> str:
    """
    Format a given name by capitalizing the first part before a colon, if present.
    """
    if ':' in name:
        return name.split(":")[0].title()
    return name.title()
