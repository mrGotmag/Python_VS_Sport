from pydantic import BaseModel, Field, EmailStr


class TeamRegisterRequest(BaseModel):
    school: str = Field(min_length=2, max_length=128)
    team_name: str = Field(min_length=2, max_length=128)
    grade: str = Field(min_length=1, max_length=64)

    leader_name: str = Field(min_length=2, max_length=128)
    leader_email: str = Field(min_length=5, max_length=128)  # Пока просто строка
    leader_phone: str | None = None

    member1_name: str = Field(min_length=2, max_length=128)
    member2_name: str = Field(min_length=2, max_length=128)