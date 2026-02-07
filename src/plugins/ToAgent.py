from typing import Any, Dict, Optional

import requests
import logging
import json

logger = logging.getLogger("ToAgent")

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
        
        # Concise Log: Request
        # Truncate query if extremely long, but typically it's short enough.
        logger.info(f"Sending Agent Request -> {query}")
        
        headers = {}
        try:
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            
            try:
                data = response.json()
                # Extract 'msg' or simple status for concise log
                msg = data.get('msg', '') if isinstance(data, dict) else str(data)
                # If data is nested, try to get inner msg
                if isinstance(data, dict) and 'data' in data and isinstance(data['data'], dict):
                     # Sometimes the inner data has useful info
                     pass
                     
                # Concise Log: Response
                logger.info(f"Agent Response <- Status: {response.status_code} | Msg: {msg}")
                
            except ValueError:
                data = response.text
                logger.info(f"Agent Response <- Status: {response.status_code} | Raw: {data[:100]}...")
                
            return {"status_code": response.status_code, "data": data}
            
        except Exception as e:
            logger.error(f"Agent Request Failed: {e}")
            return {"status_code": -1, "data": str(e)}
