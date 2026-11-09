"""Structured activity faults shared by Studio and portable Python activities."""
class MinaFault(Exception):
    def __init__(self,message: str,*,fault_type='UserDefinedException',code='',details=None,cause=None):
        super().__init__(message);self.fault_type=fault_type;self.code=code;self.details=details or {};self.cause=cause
