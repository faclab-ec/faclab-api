from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

_CONFIG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class OnboardingStepResponse(BaseModel):
    model_config = _CONFIG

    key: str = Field(
        description="branches, emission_points, terminals, users or import"
    )
    done: bool
    count: int = Field(description="How many of it the company has")
    required: bool = Field(description="A step the company can't invoice without")


class OnboardingResponse(BaseModel):
    model_config = _CONFIG

    steps: list[OnboardingStepResponse]
    ready: bool = Field(description="Every required step of core is done")
