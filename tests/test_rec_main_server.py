from scripts.migrate_rec_choque import MAIN_SERVER_URL
from scripts.provision_rec_main_server import channel_payload, message_payload


def test_ingress_channel_is_private_and_message_uses_official_link() -> None:
    channel = channel_payload(100, 200, [300])
    everyone = next(item for item in channel["permission_overwrites"] if item["id"] == "100")
    staff = next(item for item in channel["permission_overwrites"] if item["id"] == "300")
    view_channel = 1 << 10

    assert int(everyone["deny"]) & view_channel
    assert int(staff["allow"]) & view_channel

    message = message_payload()
    button = message["components"][0]["components"][0]
    assert button["url"] == MAIN_SERVER_URL == "https://choquebgr.online/discord"
    assert message["allowed_mentions"] == {"parse": []}


def test_ingress_channel_preserves_approved_member_access() -> None:
    view_channel = 1 << 10
    read_history = 1 << 16
    send_messages = 1 << 11
    approved = {
        "id": "400",
        "type": 1,
        "allow": str(view_channel | read_history),
        "deny": str(send_messages),
    }

    channel = channel_payload(100, 200, [300], [approved])

    member = next(
        item
        for item in channel["permission_overwrites"]
        if item["id"] == "400" and item["type"] == 1
    )
    assert int(member["allow"]) & view_channel
    assert int(member["allow"]) & read_history
    assert int(member["deny"]) & send_messages
