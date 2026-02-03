from typing import Any, Dict, Optional

import requests

class ToAgent:
    def __init__(
        self,
        base_url: str = "http://192.168.2.236:8088/system/employee/webhook/invoke",
        token: str = "eyJhbGciOiJIUzUxMiJ9.eyJsb2dpbl91c2VyX2tleSI6IjRkNDU4YzFhLTMxMmUtNDNkMy04NmIyLWY5OWViNDk3MmRlOCJ9.IV9adDQM4tdrOuDGkI6VtmDtwb1-73eOPJo0p-RoxOX3oUQM4ISA6OO087KA8yy1n_D-PhGEHeIXNmqNB_BXIg",
    ) -> None:
        self.base_url = base_url
        self.token = token
        
    def invoke(
        self,
        employee_id: str,
        user_id: str,
        query: str,
        business_params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        if not self.token:
            raise ValueError("token is required")
        payload = {
            "employeeId": employee_id,
            "userId": user_id,
            "query": query,
            "business_params": business_params or {"additionalProp1": {}},
        }
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        response = requests.post(
            self.base_url,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        try:
            data = response.json()
        except ValueError:
            data = response.text
        return {"status_code": response.status_code, "data": data}
