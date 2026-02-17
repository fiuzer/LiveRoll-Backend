from pydantic import BaseModel, EmailStr, Field


class RegisterForm(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginForm(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class GiveawayCreateForm(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    command: str = Field(default='!participar', min_length=2, max_length=50)
    youtube_video_id: str | None = Field(default=None, max_length=255)


class GiveawayActionForm(BaseModel):
    giveaway_id: int
