from __future__ import annotations

from dataclasses import dataclass

HISTORICAL_COURSE_CHANNEL_ID = 1162114694581059584


@dataclass(frozen=True, slots=True)
class HistoricalCourse:
    internal_code: str
    source_message_id: int
    course_role_id: int
    required_role_ids: tuple[int, ...]
    passing_score: int
    enrollment_status: str
    description: str
    notes: str


HISTORICAL_COURSES = (
    HistoricalCourse(
        "membro_aguia",
        1162971149177733250,
        1161840644394860636,
        (1161734642349637674,),
        80,
        "CLOSED",
        "Formação operacional para atuação especializada na unidade Águia.",
        "Edital histórico fechado. Nova abertura depende da gestão de cursos.",
    ),
    HistoricalCourse(
        "atirador_elite",
        1162972212706427080,
        1147057930491920404,
        (1146622062966886417,),
        80,
        "OPEN",
        "Qualificação técnica de atirador de elite da CHOQUE - BGR.",
        "Edital histórico aceitava solicitações; reprovação exige 14 dias de intervalo.",
    ),
    HistoricalCourse(
        "modulacao",
        1162973002502258728,
        1162972445888745472,
        (1146622062966886412,),
        80,
        "OPEN",
        "Formação de modulação e comunicação operacional da CHOQUE - BGR.",
        "Edital histórico aberto; reprovação exige 14 dias de intervalo.",
    ),
    HistoricalCourse(
        "membro_rocam",
        1164744520152399953,
        1161841078069121115,
        (1146622062966886417,),
        80,
        "OPEN",
        "Formação operacional para ingresso e atuação na unidade ROCAM.",
        "Edital histórico externo importado para o fluxo interno; intervalo de 14 dias.",
    ),
    HistoricalCourse(
        "p1_tatico",
        1164744630357729401,
        1146622062912344089,
        (1146622062966886417, 1147057821020590100),
        80,
        "OPEN",
        "Qualificação de P1 Tático para atuação especializada de inteligência operacional.",
        "Exige Praça Graduado e P1 Oficial; intervalo de 14 dias após reprovação.",
    ),
    HistoricalCourse(
        "p1_oficial",
        1164744837615067166,
        1147057821020590100,
        (1146622062966886417,),
        80,
        "OPEN",
        "Formação de P1 Oficial para atividades de inteligência da corporação.",
        "Edital histórico aberto; reprovação exige 14 dias de intervalo.",
    ),
    HistoricalCourse(
        "rocam_elite",
        1165179130631946321,
        1165176915502571571,
        (1146622062966886417,),
        90,
        "CLOSED",
        "Qualificação avançada de elite da unidade ROCAM.",
        "Edital histórico indisponível. Nova abertura depende da gestão de cursos.",
    ),
    HistoricalCourse(
        "abordagem_basica",
        1165694382054322258,
        1165358478227939338,
        (1146622062966886412,),
        90,
        "OPEN",
        "Formação fundamental de abordagem e procedimentos operacionais.",
        "Edital histórico aceitava solicitações; intervalo de 14 dias após reprovação.",
    ),
    HistoricalCourse(
        "abordagem_avancada",
        1165694524622913677,
        1165360167815229511,
        (1165358478227939338,),
        90,
        "OPEN",
        "Formação avançada de abordagem para membros já qualificados no nível básico.",
        "Exige Abordagem Básica; intervalo de 14 dias após reprovação.",
    ),
)

COURSE_DISPLAY_NAMES = {
    "membro_aguia": "Membro Águia",
    "atirador_elite": "Atirador de Elite",
    "modulacao": "Modulação",
    "membro_rocam": "Membro ROCAM",
    "p1_tatico": "P1 Tático",
    "p1_oficial": "P1 Oficial",
    "rocam_elite": "ROCAM Elite",
    "abordagem_basica": "Abordagem Básica",
    "abordagem_avancada": "Abordagem Avançada",
}
