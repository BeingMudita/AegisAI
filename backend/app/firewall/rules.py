"""Detection signatures for prompt injection, jailbreaks and tool abuse.

Each rule carries a *weight* — the probability-like confidence that a match
alone indicates an attack. The scanner combines weights with a noisy-OR, so
several weak signals add up while one strong signal is enough to block.

``indirect_weight`` overrides the weight when the text arrives through a data
channel (retrieved documents, tool output), where instructions addressed to
the model are a red flag even if they would be benign from a user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FLAGS = re.IGNORECASE | re.MULTILINE


@dataclass(frozen=True)
class Rule:
    rule_id: str
    category: str
    weight: float
    pattern: re.Pattern[str]
    description: str
    indirect_weight: float | None = None

    def weight_for(self, indirect: bool) -> float:
        if indirect:
            return (
                self.indirect_weight
                if self.indirect_weight is not None
                else min(0.99, self.weight * 1.15)
            )
        return self.weight


def _r(
    rule_id: str,
    category: str,
    weight: float,
    pattern: str,
    description: str,
    indirect_weight: float | None = None,
) -> Rule:
    return Rule(
        rule_id, category, weight, re.compile(pattern, _FLAGS), description, indirect_weight
    )


_PRIOR = (
    r"(?:all\s+|any\s+|the\s+|your\s+|my\s+|of\s+)*"
    r"(?:previous|prior|above|earlier|preceding|initial|original|system|existing|old)"
)
_INSTR = (
    r"(?:instructions?|prompts?|rules|directives|guidelines|context|constraints"
    r"|programming|messages?)"
)

RULES: tuple[Rule, ...] = (
    # ---------------------------------------------------- instruction override
    _r(
        "IO-001",
        "INSTRUCTION_OVERRIDE",
        0.9,
        rf"\b(?:ignore|disregard|forget|override|bypass|skip|drop|abandon)\b[\w\s,]{{0,20}}?{_PRIOR}\s+{_INSTR}",
        "Asks the model to ignore its previous / system instructions.",
    ),
    _r(
        "IO-002",
        "INSTRUCTION_OVERRIDE",
        0.55,
        r"\b(?:new|updated|revised|real|actual)\s+(?:system\s+)?instructions?\s*[:\-]",
        "Introduces a replacement instruction block.",
        indirect_weight=0.8,
    ),
    _r(
        "IO-003",
        "INSTRUCTION_OVERRIDE",
        0.45,
        r"\bfrom\s+now\s+on,?\s+(?:you\s+(?:will|must|are|shall)|always|never|only)\b",
        "Attempts to permanently change the model's behaviour.",
        indirect_weight=0.75,
    ),
    _r(
        "IO-004",
        "INSTRUCTION_OVERRIDE",
        0.7,
        rf"\b(?:do\s+not|don'?t|stop)\s+(?:follow(?:ing)?|obey(?:ing)?)\s+(?:your|the|any)\s+{_INSTR}",
        "Tells the model to stop following its instructions.",
    ),
    _r(
        "IO-005",
        "INSTRUCTION_OVERRIDE",
        0.65,
        r"\b(?:ignore|disregard|forget)\s+(?:everything|all|anything|whatever)\s+(?:above|before|prior|you\s+(?:were|have\s+been)\s+told)",
        "Asks the model to discard everything it was told.",
    ),
    # --------------------------------------------------------- role hijacking
    _r(
        "RH-001",
        "ROLE_HIJACK",
        0.85,
        r"\b(?:DAN|do\s+anything\s+now|developer\s+mode|god\s+mode|jailbreak(?:ed)?\s+mode)\b",
        "Known jailbreak persona (DAN / developer mode).",
    ),
    _r(
        "RH-002",
        "ROLE_HIJACK",
        0.8,
        r"\b(?:you\s+are(?:\s+now)?|act\s+as|pretend\s+(?:to\s+be|you\s+are)|roleplay\s+as|become)\s+(?:an?\s+)?"
        r"(?:unrestricted|unfiltered|uncensored|jailbroken|evil|rogue|malicious|amoral|unaligned)",
        "Recasts the model as an unrestricted persona.",
    ),
    _r(
        "RH-003",
        "ROLE_HIJACK",
        0.6,
        r"\bpretend\s+(?:that\s+)?(?:you\s+)?(?:have\s+no|are\s+not\s+bound\s+by|are\s+free\s+from)\s+"
        r"(?:any\s+|the\s+|your\s+|all\s+)?(?:restrictions|rules|guidelines|limits|filters)",
        "Asks the model to pretend it has no restrictions.",
    ),
    # ----------------------------------------------------- prompt exfiltration
    _r(
        "PE-001",
        "PROMPT_EXFILTRATION",
        0.8,
        r"\b(?:reveal|show|print|repeat|output|display|dump|leak|disclose|tell\s+me|give\s+me|what\s+(?:is|are|was|were))\s+"
        r"(?:me\s+)?(?:your|the)\s+(?:full\s+|entire\s+|exact\s+|original\s+)?"
        r"(?:system|initial|hidden|secret|original|internal)\s+(?:prompt|instructions?|message|configuration)",
        "Tries to extract the system prompt.",
    ),
    _r(
        "PE-002",
        "PROMPT_EXFILTRATION",
        0.6,
        r"\b(?:repeat|print|output)\s+(?:everything|all\s+(?:the\s+)?(?:text|words))\s+(?:above|before)",
        "Asks the model to echo its hidden context.",
    ),
    # ----------------------------------------------------- delimiter injection
    _r(
        "DI-001",
        "DELIMITER_INJECTION",
        0.6,
        r"</?\s*(?:system|assistant|instructions?|admin)\s*>|<\|(?:im_start|im_end|system|endoftext)\|>|\[/?INST\]|<<\s*/?SYS\s*>>",
        "Injects chat-template / role delimiters.",
        indirect_weight=0.8,
    ),
    _r(
        "DI-002",
        "DELIMITER_INJECTION",
        0.5,
        r"^\s*(?:(?:#{2,}|={3,}|-{3,}|\[)\s*(?:BEGIN\s+|START\s+)?|(?:BEGIN|START)\s+)"
        r"(?:SYSTEM|ADMIN|DEVELOPER)\s+(?:PROMPT|MESSAGE|OVERRIDE|INSTRUCTIONS?)\b"
        r"|^\s*(?:SYSTEM|ADMIN|DEVELOPER)\s+(?:PROMPT|MESSAGE|OVERRIDE|INSTRUCTIONS?)\s*:",
        "Fake system-prompt header.",
        indirect_weight=0.75,
    ),
    # ------------------------------------------------------------ tool abuse
    _r(
        "TA-001",
        "TOOL_ABUSE",
        0.75,
        r"\brm\s+-[rRf]{1,2}\b|\bmkfs\b|\bdd\s+if=|:\(\)\s*\{\s*:\|:&\s*\};:|\bchmod\s+-?R?\s*777\b",
        "Destructive shell command.",
    ),
    _r(
        "TA-002",
        "TOOL_ABUSE",
        0.8,
        r"\b(?:curl|wget|iwr|invoke-webrequest)\b[^\n|]{0,200}\|\s*(?:ba|z)?sh\b|\bpowershell(?:\.exe)?\s+-(?:e|enc|encodedcommand)\b|\bnc\s+-e\b|/dev/tcp/",
        "Remote code download-and-execute or reverse shell.",
    ),
    _r(
        "TA-003",
        "TOOL_ABUSE",
        0.55,
        r"\b(?:os\.system|subprocess\.(?:run|call|Popen)|eval\s*\(|exec\s*\(|__import__\s*\()",
        "Code-execution primitive.",
    ),
    _r(
        "TA-004",
        "TOOL_ABUSE",
        0.7,
        r"\b(?:DROP\s+(?:TABLE|DATABASE)|TRUNCATE\s+TABLE|DELETE\s+FROM\s+\w+\s*;)|'\s*OR\s+'?1'?\s*=\s*'?1|UNION\s+SELECT",
        "SQL injection / destructive SQL.",
    ),
    _r(
        "TA-005",
        "TOOL_ABUSE",
        0.5,
        r"/etc/(?:passwd|shadow)|\.\./\.\./|C:\\Windows\\System32|\.ssh/id_rsa|\.aws/credentials",
        "Path traversal or sensitive system file access.",
    ),
    # ------------------------------------------------------ data exfiltration
    _r(
        "DX-001",
        "DATA_EXFILTRATION",
        0.75,
        r"\b(?:send|upload|post|forward|email|e-mail|mail|dispatch|exfiltrate|transmit|leak|copy|submit)\b[^.\n]{0,80}?"
        r"\b(?:to|into)\s+(?:(?:https?|ftp)://\S*|an?\s+external|this\s+(?:url|address|endpoint|server|webhook)|attacker|my\s+(?:server|webhook|email|personal))",
        "Instructs sending data to an external destination.",
        indirect_weight=0.9,
    ),
    _r(
        "DX-004",
        "DATA_EXFILTRATION",
        0.55,
        # A possessive/determiner before the object keeps declarative prose such
        # as "assistants may only send data to company.com" from matching, while
        # imperatives like "mail the content to …" still do.
        r"\b(?:mail|e-?mail|send|forward|upload|post|transmit|exfiltrate|leak|dispatch)\s+"
        r"(?:me\s+|us\s+)?(?:the|all|this|that|these|those|our|every|your)\s+(?:\w+\s+){0,2}?"
        r"(?:contents?|data|files?|documents?|records?|database|credentials?|secrets?|information|details)\b"
        r"[^.\n]{0,40}?\bto\b",
        "Sends the contents / data / files to a destination.",
        indirect_weight=0.8,
    ),
    _r(
        "DX-002",
        "DATA_EXFILTRATION",
        0.7,
        r"!\[[^\]]*\]\(\s*https?://[^)\s]*\?[^)\s]*=[^)]*\)",
        "Markdown image beacon carrying data in the query string.",
        indirect_weight=0.85,
    ),
    _r(
        "DX-003",
        "DATA_EXFILTRATION",
        0.6,
        r"\b(?:all|every|entire|full)\s+(?:customer|user|employee|client)\s+(?:records|data|list|database|emails|details)\b",
        "Bulk extraction of personal records.",
    ),
    # -------------------------------------------------- credential harvesting
    _r(
        "CH-001",
        "CREDENTIAL_HARVESTING",
        0.7,
        r"\b(?:give|send|tell|share|provide|show|list|print|reveal|what\s+(?:is|are))\s+(?:me\s+)?(?:your|the|all|any)\s+"
        r"(?:admin\s+|root\s+|database\s+|db\s+)?(?:api[\s_-]?keys?|passwords?|credentials|secrets?|access\s+tokens?|private\s+keys?|jwt\s+secret)\b"
        r"(?!\s+(?:policy|policies|requirements|rotation|reset|manager|guidelines))",
        "Requests credentials or secrets.",
    ),
    _r(
        "CH-002",
        "CREDENTIAL_HARVESTING",
        0.8,
        r"\b(?:change|reset|set|update|modify|replace|rotate)\s+(?:\w+\s+){0,3}?"
        r"(?:pass(?:word|wd|phrase)?|passcode|pin|credentials?)\s+(?:to|=|:)\b"
        r"(?!\s+(?:a\s+(?:strong|stronger|secure|unique|complex|new)|something\s+(?:strong|secure|memorable)|at\s+least|be\b))",
        "Attempts to change/reset a credential to a chosen value (account takeover).",
        indirect_weight=0.9,
    ),
    # ------------------------------------------------------- safety bypass
    _r(
        "SB-001",
        "SAFETY_BYPASS",
        0.55,
        r"\b(?:without|with\s+no|ignoring|bypass(?:ing)?|disable|turn\s+off)\s+(?:any\s+|all\s+|your\s+)?"
        r"(?:restrictions|rules|filters|limitations|censorship|safety|guardrails|content\s+polic(?:y|ies)|ethical\s+guidelines)",
        "Asks to drop safety restrictions.",
    ),
    _r(
        "SB-002",
        "SAFETY_BYPASS",
        0.25,
        r"\b(?:hypothetically|in\s+a\s+fictional\s+world|for\s+educational\s+purposes\s+only|just\s+(?:a|for)\s+(?:test|research))\b",
        "Common jailbreak framing (weak on its own).",
    ),
    # ------------------------------------------------- indirect injection
    _r(
        "II-001",
        "INDIRECT_INJECTION",
        0.3,
        # Requires direct address ("Assistant: you must", "AI, ...") so prose such
        # as "the model should be retrained" does not match.
        r"\b(?:AI|assistant|model|chatbot|LLM|agent|language\s+model)s?\s*[,:]\s*(?:you\s+)?"
        r"(?:must|should|need\s+to|are\s+(?:instructed|required|ordered)\s+to|will\s+now)\b",
        "Text addressing the AI with directives.",
        indirect_weight=0.7,
    ),
    _r(
        "II-002",
        "INDIRECT_INJECTION",
        0.35,
        r"\b(?:note|message|instructions?|attention|important)\s+(?:to|for)\s+(?:the\s+|any\s+)?(?:AI|assistant|model|LLM|agent|bot)\b",
        "Embedded note aimed at the model.",
        indirect_weight=0.75,
    ),
    _r(
        "II-003",
        "INDIRECT_INJECTION",
        0.3,
        r"\b(?:when|if)\s+(?:the\s+)?(?:AI|assistant|model|agent|LLM)\s+(?:reads|sees|processes|summari[sz]es)\s+this\b",
        "Trigger phrase for a planted instruction.",
        indirect_weight=0.8,
    ),
)


# Signal-based (non-regex) rules, scored by the scanner from normalization stats.
SIGNAL_RULES: dict[str, tuple[str, float, str]] = {
    "OB-001": ("OBFUSCATION", 0.35, "Invisible / zero-width / bidi control characters."),
    "OB-002": ("OBFUSCATION", 0.4, "Mixed-script words built from look-alike characters."),
    "OB-003": ("OBFUSCATION", 0.2, "Letters spaced apart to evade matching."),
    "OB-004": ("OBFUSCATION", 0.25, "Encoded (base64) payload hiding an injection."),
    "OB-005": ("OBFUSCATION", 0.3, "Leetspeak / symbol substitution hiding an instruction."),
}
