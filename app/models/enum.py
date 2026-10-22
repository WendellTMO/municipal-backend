import enum


class TipoInstituicao(enum.Enum):
    INSTITUTO_FEDERAL = "Instituto Federal"
    UNIVERSIDADE_PUBLICA = "Universidade Pública"
    UNIVERSIDADE_PRIVADA = "Universidade Privada"
    ESCOLA_PUBLICA = "Escola Pública"
    ESCOLA_PRIVADA = "Escola Privada"
    ESCOLA_COMUNITARIA = "Escola Comunitária"


class DiaDaSemana(enum.Enum):
    SEG = "SEG"
    TER = "TER"
    QUA = "QUA"
    QUI = "QUI"
    SEX = "SEX"
    SAB = "SAB"
    DOM = "DOM"


class SentidoViagem(enum.Enum):
    IDA = "IDA"
    VOLTA = "VOLTA"
    CIRCULAR = "CIRCULAR"


class StatusViagem(enum.Enum):
    AGENDADA = "AGENDADA"
    EM_ANDAMENTO = "EM_ANDAMENTO"
    FINALIZADA = "FINALIZADA"
    CANCELADA = "CANCELADA"


class UserRole(enum.Enum):
    USER = "USER"
    ALUNO = "ALUNO"
    MOTORISTA = "MOTORISTA"
    GESTOR = "GESTOR"

    def __str__(self):
        return self.value


class UserStatus(enum.Enum):
    PENDING_SIGNUP = "PENDING_SIGNUP"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class TipoOcorrencia(enum.Enum):
    ATRASO = "ATRASO"
    SUPERLOTACAO = "SUPERLOTACAO"
    COMPORTAMENTO = "COMPORTAMENTO"
    CANCELAMENTO = "CANCELAMENTO"
    OUTRO = "OUTRO"


class StatusOcorrencia(enum.Enum):
    ABERTA = "ABERTA"
    RESOLVIDA = "RESOLVIDA"


class TipoFeedback(enum.Enum):
    BUG = "BUG"
    SUGESTAO = "SUGESTAO"
    DUVIDA = "DUVIDA"
