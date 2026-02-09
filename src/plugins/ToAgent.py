from typing import Any, Dict, Optional

import requests
import logging
import json

logger = logging.getLogger("ToAgent")

class ToAgent:
    def __init__(
        self,
        module_name: str = "UnknownModule",
        employee_id: str = "2019323642451259394",
        user_id: str = "1868",
        base_url: str = "http://scenemana.lzwcai.com/api/system/employee/webhook/invoke",
    ) -> None:
        self.module_name = module_name
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
        
        # Enhanced Log: Request
        # ANSI Colors: \033[96m (Cyan) for Request, \033[94m (Blue) for Response, \033[0m (Reset)
        COLOR_REQ = "\033[96m"
        COLOR_RES = "\033[94m"
        COLOR_RESET = "\033[0m"

        log_req = (
            f"\n{COLOR_REQ}{'='*30}\n"
            f"[POST] Module: {self.module_name}\n"
            f"Sending: {query}\n"
            f"{'='*30}{COLOR_RESET}"
        )
        logger.info(log_req)
        
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
                
                # Enhanced Log: Response
                log_resp = (
                    f"\n{COLOR_RES}{'='*30}\n"
                    f"[POST] Module: {self.module_name}\n"
                    f"Server Response (Status {response.status_code}): {msg}\n"
                    f"Full Data: {json.dumps(data, ensure_ascii=False)}\n"
                    f"{'='*30}{COLOR_RESET}"
                )
                logger.info(log_resp)
                
            except ValueError:
                data = response.text
                logger.info(
                    f"\n{COLOR_RES}{'='*30}\n"
                    f"[POST] Module: {self.module_name}\n"
                    f"Server Response (Status {response.status_code}): {data[:200]}...\n"
                    f"{'='*30}{COLOR_RESET}"
                )
                
            return {"status_code": response.status_code, "data": data}
            
        except Exception as e:
            logger.error(f"Agent Request Failed: {e}")
            return {"status_code": -1, "data": str(e)}
