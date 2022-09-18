from enum import Enum


class AlertOrigin(Enum):
    catchup = "catchup"
    callback = "callback"
    unavailable = "unavailable"


class BroadcasterType(Enum):
    partner = "partner"
    affiliate = "affiliate"
    none = ''


class UserType(Enum):
    staff = "staff"
    admin = "admin"
    global_mod = "global_mod"
    none = ""


class Live(Enum):
    live = "live"
    none = ""


class SubscriptionMethod(Enum):
    webhook = "webhook"


class SubscriptionStatus(Enum):
    verification_pending = "webhook_callback_verification_pending"
    enabled = "enabled"
    verification_failed = "webhook_callback_verification_failed"
    failures_exceeded = "notification_failures_exceeded"
    authorization_revoked = "authorization_revoked"
    user_removed = "user_removed"


class SubscriptionType(Enum):
    # https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types
    CHANNEL_UPDATE = "channel.update"
    CHANNEL_FOLLOW = "channel.follow"
    CHANNEL_SUBSCRIBE = "channel.subscribe"
    CHANNEL_SUBSCRIPTION_END = "channel.subscription.end"
    CHANNEL_SUBSCRIPTION_GIFT = "channel.subscription.gift"
    CHANNEL_SUBSCRIPTION_MESSAGE = "channel.subscription.message"
    CHANNEL_CHEER = "channel.cheer"
    CHANNEL_RAID = "channel.raid"
    CHANNEL_BAN = "channel.ban"
    CHANNEL_UNBAN = "channel.unban"
    CHANNEL_MODERATOR_ADD = "channel.moderator.add"
    CHANNEL_MODERATOR_REMOVE = "channel.moderator.remove"
    CHANNEL_POINTS_CUSTOM_REWARD_ADD = "channel.channel_points_custom_reward.add"
    CHANNEL_POINTS_CUSTOM_REWARD_UPDATE = "channel.channel_points_custom_reward.update"
    CHANNEL_POINTS_CUSTOM_REWARD_REMOVE = "channel.channel_points_custom_reward.remove"
    CHANNEL_POINTS_CUSTOM_REWARD_REDEMPTION_ADD = "channel.channel_points_custom_reward_redemption.add"
    CHANNEL_POINTS_CUSTOM_REWARD_REDEMPTION_UPDATE = "channel.channel_points_custom_reward_redemption.update"
    CHANNEL_POLL_BEGIN = "channel.poll.begin"
    CHANNEL_POLL_PROGRESS = "channel.poll.progress"
    CHANNEL_POLL_END = "channel.poll.end"
    CHANNEL_PREDICTION_BEGIN = "channel.prediction.begin"
    CHANNEL_PREDICTION_PROGRESS = "channel.prediction.progress"
    CHANNEL_PREDICTION_LOCK = "channel.prediction.lock"
    CHANNEL_PREDICTION_END = "channel.prediction.end"
    DROP_ENTITLEMENT_GRANT = "drop.entitlement.grant"
    EXTENSION_BITS_TRANSACTION_CREATE = "extension.bits_transaction.create"
    GOAL_BEGIN = "channel.goal.begin"
    GOAL_PROGRESS = "channel.goal.progress"
    GOAL_END = "channel.goal.end"
    HYPE_TRAIN_BEGIN = "channel.hype_train.begin"
    HYPE_TRAIN_PROGRESS = "channel.hype_train.progress"
    HYPE_TRAIN_END = "channel.hype_train.end"
    STREAM_ONLINE = "stream.online"
    STREAM_OFFLINE = "stream.offline"
    USER_AUTHORIZATION_GRANT = "user.authorization.grant"
    USER_AUTHORIZATION_REVOKE = "user.authorization.revoke"
    USER_UPDATE = "user.update"


class AlertType(Enum):
    title = "titlecallback"
    status = "callback"


class Languages(Enum):
    AA = "Afar"
    AB = "Abkhazian"
    AF = "Afrikaans"
    AK = "Akan"
    SQ = "Albanian"
    AM = "Amharic"
    AR = "Arabic"
    AN = "Aragonese"
    HY = "Armenian"
    AS = "Assamese"
    AV = "Avaric"
    AE = "Avestan"
    AY = "Aymara"
    AZ = "Azerbaijani"
    BA = "Bashkir"
    BM = "Bambara"
    EU = "Basque"
    BE = "Belarusian"
    BN = "Bengali"
    BH = "Bihari languages"
    BI = "Bislama"
    BO = "Tibetan"
    BS = "Bosnian"
    BR = "Breton"
    BG = "Bulgarian"
    MY = "Burmese"
    CA = "Catalan; Valencian"
    CS = "Czech"
    CH = "Chamorro"
    CE = "Chechen"
    ZH = "Chinese"
    CU = "Church Slavic; Old Slavonic; Church Slavonic; Old Bulgarian; Old Church Slavonic"
    CV = "Chuvash"
    KW = "Cornish"
    CO = "Corsican"
    CR = "Cree"
    CY = "Welsh"
    DA = "Danish"
    DE = "German"
    DV = "Divehi; Dhivehi; Maldivian"
    NL = "Dutch; Flemish"
    DZ = "Dzongkha"
    EL = "Greek"
    EN = "English"
    EO = "Esperanto"
    ET = "Estonian"
    EE = "Ewe"
    FO = "Faroese"
    FA = "Persian"
    FJ = "Fijian"
    FI = "Finnish"
    FR = "French"
    FY = "Western Frisian"
    FF = "Fulah"
    GD = "Gaelic; Scottish Gaelic"
    GA = "Irish"
    GL = "Galician"
    GV = "Manx"
    GN = "Guarani"
    GU = "Gujarati"
    HT = "Haitian; Haitian Creole"
    HA = "Hausa"
    HE = "Hebrew"
    HZ = "Herero"
    HI = "Hindi"
    HO = "Hiri Motu"
    HR = "Croatian"
    HU = "Hungarian"
    IG = "Igbo"
    IS = "Icelandic"
    IO = "Ido"
    II = "Sichuan Yi; Nuosu"
    IU = "Inuktitut"
    IE = "Interlingue; Occidental"
    IA = "Interlingua International Auxiliary Language Association)"
    ID = "Indonesian"
    IK = "Inupiaq"
    IT = "Italian"
    JV = "Javanese"
    JA = "Japanese"
    KL = "Kalaallisut; Greenlandic"
    KN = "Kannada"
    KS = "Kashmiri"
    KA = "Georgian"
    KR = "Kanuri"
    KK = "Kazakh"
    KM = "Central Khmer"
    KI = "Kikuyu; Gikuyu"
    RW = "Kinyarwanda"
    KY = "Kirghiz; Kyrgyz"
    KV = "Komi"
    KG = "Kongo"
    KO = "Korean"
    KJ = "Kuanyama; Kwanyama"
    KU = "Kurdish"
    LO = "Lao"
    LA = "Latin"
    LV = "Latvian"
    LI = "Limburgan; Limburger; Limburgish"
    LN = "Lingala"
    LT = "Lithuanian"
    LB = "Luxembourgish; Letzeburgesch"
    LU = "Luba-Katanga"
    LG = "Ganda"
    MK = "Macedonian"
    MH = "Marshallese"
    ML = "Malayalam"
    MI = "Maori"
    MR = "Marathi"
    MS = "Malay"
    MG = "Malagasy"
    MT = "Maltese"
    MN = "Mongolian"
    NA = "Nauru"
    NV = "Navajo; Navaho"
    NR = "Ndebele"
    ND = "Ndebele"
    NG = "Ndonga"
    NE = "Nepali"
    NN = "Norwegian Nynorsk; Nynorsk"
    NB = "Bokmål"
    NO = "Norwegian"
    OC = "Occitan post 1500)"
    OJ = "Ojibwa"
    OR = "Oriya"
    OM = "Oromo"
    OS = "Ossetian; Ossetic"
    PA = "Panjabi; Punjabi"
    PI = "Pali"
    PL = "Polish"
    PT = "Portuguese"
    PS = "Pushto; Pashto"
    QU = "Quechua"
    RM = "Romansh"
    RO = "Romanian; Moldavian; Moldovan"
    RN = "Rundi"
    RU = "Russian"
    SG = "Sango"
    SA = "Sanskrit"
    SI = "Sinhala; Sinhalese"
    SK = "Slovak"
    SL = "Slovenian"
    SE = "Northern Sami"
    SM = "Samoan"
    SN = "Shona"
    SD = "Sindhi"
    SO = "Somali"
    ST = "Sotho"
    ES = "Spanish; Castilian"
    SC = "Sardinian"
    SR = "Serbian"
    SS = "Swati"
    SU = "Sundanese"
    SW = "Swahili"
    SV = "Swedish"
    TY = "Tahitian"
    TA = "Tamil"
    TT = "Tatar"
    TE = "Telugu"
    TG = "Tajik"
    TL = "Tagalog"
    TH = "Thai"
    TI = "Tigrinya"
    TO = "Tonga Tonga Islands)"
    TN = "Tswana"
    TS = "Tsonga"
    TK = "Turkmen"
    TR = "Turkish"
    TW = "Twi"
    UG = "Uighur; Uyghur"
    UK = "Ukrainian"
    UR = "Urdu"
    UZ = "Uzbek"
    VE = "Venda"
    VI = "Vietnamese"
    VO = "Volapük"
    WA = "Walloon"
    WO = "Wolof"
    XH = "Xhosa"
    YI = "Yiddish"
    YO = "Yoruba"
    ZA = "Zhuang; Chuang"
    ZU = "Zulu"
    OTHER = "Other"


class VideoType(Enum):
    upload = "upload"
    archive = "archive"
    highlight = "highlight"


class VideoPrivacy(Enum):
    public = "public"
    private = "private"


class TitleCache(Enum):
    title: str
    game: str


class ChannelCache(Enum):
    alert_cooldown: int
    user_login: str
    stream_id: int
    is_live: bool
    live_channels: list[int]
    live_alerts: dict[str, int]
    last_update: int
    games: dict[str, int]
    reusable_alerts: list[dict[str, int]]


class YoutubeChannelCache(Enum):
    alert_cooldown: int
    channel_id: str
    video_id: int
    is_live: bool
    live_channels: list[int]
    live_alerts: dict[str, int]
    last_update: int
    reusable_alerts: list[dict[str, int]]
