from typing import Final, Literal, NotRequired, TypedDict, cast

import nextcord
from nextcord.components import InteractiveComponent
from nextcord.enums import ComponentType, TextInputStyle, try_enum
from nextcord.types import components as comp_payloads
from nextcord.utils import MISSING


class RadioOption(TypedDict):
    label: str
    value: str
    description: NotRequired[str]
    default: NotRequired[bool]


RADIO_GROUP_COMPONENT_TYPE: Final[int] = 21


class RadioGroupComponent(TypedDict):
    type: Literal[21]
    id: int | None
    custom_id: str
    options: list[RadioOption]
    required: bool | None
    value: str | None


class RadioGroup(InteractiveComponent):  # Component type 21
    def __init__(
        self,
        options: list[RadioOption],
        custom_id: str | None = None,
        *,
        required: bool = True,
        value: str = MISSING,
        component_id: int = MISSING,
    ) -> None:
        super().__init__(
            custom_id,
            component_type=RADIO_GROUP_COMPONENT_TYPE,
            component_id=component_id,
        )
        self.options = options
        self.required = required
        self.value = value

    def to_dict(self) -> RadioGroupComponent:  # type: ignore[override]
        ret = cast(RadioGroupComponent, super().to_dict())

        ret["options"] = self.options

        if self.required is not MISSING:
            ret["required"] = self.required

        if self.value is not MISSING:
            ret["value"] = self.value

        return ret

    @classmethod
    def from_dict(cls, payload: RadioGroupComponent):  # type: ignore[override]
        return cls(
            payload["options"],
            payload["custom_id"],
            required=payload.get("required") or MISSING,
            value=payload.get("value") or MISSING,
            component_id=payload.get("id") or MISSING,
        )
