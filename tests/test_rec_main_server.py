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
