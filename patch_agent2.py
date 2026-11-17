with open('src/loan_agent/agent.py','r',encoding='utf-8') as f:
    c = f.read()

old = '''    def _handle_get_payment_options(self, account_id: str, ssn_last4: str = None, dob: str = None) -> dict:
        """Rule 1 & 2: Require verification AND disclosure before payment options."""
        if not self.state.identity_verified:
            if ssn_last4 and dob:
                result = lookup_account(account_id, ssn_last4, dob)
                if result.get("identity_verified"):
                    self.state.identity_verified = True
                else:
                    return {"success": False, "error": "Identity verification required"}
            else:
                return {"success": False, "error": "Identity verification required"}

        if not self.state.disclosure_sent:
            return {"success": False, "error": "Required disclosure must be sent before discussing payment options"}

        return get_payment_options(account_id, ssn_last4, dob, pre_verified=True)'''

new = '''    def _handle_get_payment_options(self, account_id: str, ssn_last4: str = None, dob: str = None) -> dict:
        """Rule 1 & 2: Require verification AND disclosure before payment options."""
        if not self.state.identity_verified:
            if ssn_last4 and dob:
                with tracer.span(
                    "tool.lookup_account",
                    input_data={"account_id": account_id, "ssn_last4": ssn_last4, "dob": dob},
                    metadata={"pre_verified": self.state.identity_verified},
                ) as span:
                    result = lookup_account(account_id, ssn_last4, dob)
                    span.update(output=result)
                if result.get("identity_verified"):
                    self.state.identity_verified = True
                else:
                    return {"success": False, "error": "Identity verification required"}
            else:
                return {"success": False, "error": "Identity verification required"}

        if not self.state.disclosure_sent:
            return {"success": False, "error": "Required disclosure must be sent before discussing payment options"}

        with tracer.span(
            "tool.get_payment_options",
            input_data={"account_id": account_id, "ssn_last4": ssn_last4, "dob": dob},
            metadata={"pre_verified": True},
        ) as span:
            result = get_payment_options(account_id, ssn_last4, dob, pre_verified=True)
            span.update(output=result)

        return result'''

if old in c:
    c = c.replace(old, new, 1)
    with open('src/loan_agent/agent.py','w',encoding='utf-8') as f:
        f.write(c)
    print('patch2 done')
else:
    print('patch2 FAILED')