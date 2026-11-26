"""Public activity entries contain concise rationale, never hidden reasoning."""
from ..db.repositories import Repository

class ActivityService:
    def __init__(self,repo:Repository):self.repo=repo
    def timeline(self,return_id:str):return self.repo.activities(return_id)
