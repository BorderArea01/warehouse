from typing import Any, Dict, Optional

import requests

class ToAgent:
    def __init__(
        self,
        employee_id: str = "2019323642451259394",
        user_id: str = "1868",
        base_url: str = "http://scenemana.lzwcai.com/api/system/employee/webhook/invoke",
    ) -> None:
        self.base_url = base_url
        self.employee_id = employee_id
        self.user_id = user_id
        
    def invoke(
        self,
        query: str,
        business_params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        payload = {
            "employeeId": self.employee_id,
            "userId": self.user_id,
            "query": query,
            "business_params": business_params or {"additionalProp1": {}},
        }
        headers = {}
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
