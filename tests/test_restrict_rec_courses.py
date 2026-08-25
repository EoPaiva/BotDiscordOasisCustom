from scripts.migrate_rec_choque import CHANNELS
from scripts.restrict_rec_courses import build_course_access_plan


def _role(role_id: int, name: str) -> dict[str, object]:
    return {"id": str(role_id), "name": name, "type": 0}


def _channel(
    channel_id: int, name: str, channel_type: int, *, parent_id: int | None = None
) -> dict[str, object]:
    return {
        "id": str(channel_id),
        "name": name,
        "type": channel_type,
        "parent_id": str(parent_id) if parent_id else None,
        "permission_overwrites": [],
    }


def test_course_plan_limits_public_channels_to_members_and_staff() -> None:
    from choque.channel_names import format_category_name, format_channel_name

    guild_id = 100
    roles = [
        _role(guild_id, "@everyone"),
        _role(200, "Membro Choque"),
        _role(201, "Comando REC"),
        _role(202, "Responsável Recrutamento"),
        _role(203, "Auxiliar Recrutamento"),
        _role(204, "Instrutor de Cursos"),
    ]
    category_id = 300
    channels = [_channel(category_id, format_category_name(3, "Cursos"), 4)]
    for index, spec in enumerate((item for item in CHANNELS if item.category == "courses"), 1):
        channels.append(
            _channel(
                category_id + index,
                format_channel_name(spec.label, spec.emoji),
                2 if spec.voice else 0,
                parent_id=category_id,
            )
        )

    plan = build_course_access_plan(guild_id, roles, channels)

    assert len(plan) == 10
    catalog = next(item for item in plan if item["channel"]["id"] == "301")
    overwrites = catalog["permission_overwrites"]
    everyone = next(item for item in overwrites if item["id"] == str(guild_id))
    member = next(item for item in overwrites if item["id"] == "200")
    view_channel = 1 << 10
    assert int(everyone["deny"]) & view_channel
    assert int(member["allow"]) & view_channel
