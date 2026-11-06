"""OpenAI Chat Completions transport with conservative budget accounting.
No persistent API keys. No pricing claims: rates are user configured estimates.
"""
import json,os,math,urllib.request,urllib.error

class BudgetError(RuntimeError):pass
class LLMError(RuntimeError):pass

class Client:
    def __init__(self,key=None,model=None,budget_usd=1.0,input_per_million=0.40,output_per_million=1.60,allow_upload=False,base_url=None):
        self.key=key or os.getenv('DEEPSEEK_API_KEY') or os.getenv('OPENAI_API_KEY','')
        self.model=model or os.getenv('DEEPSEEK_MODEL','deepseek-chat')
        self.base_url=(base_url or os.getenv('DEEPSEEK_BASE_URL','https://api.deepseek.com')).rstrip('/')
        self.budget=float(budget_usd)
        self.input_rate=float(input_per_million);self.output_rate=float(output_per_million)
        if any(not math.isfinite(v) or v<0 for v in (self.budget,self.input_rate,self.output_rate)):
            raise ValueError('预算和费率必须是有限的非负数字')
        self.allow_upload=allow_upload
        self.spent_estimate=0.0;self.usage=[]
    def estimate(self,payload,completion_tokens=1800):
        if type(completion_tokens) is not int or completion_tokens<=0:
            raise ValueError('输出 token 上限必须是正整数')
        # UTF-8 char-to-token heuristic deliberately conservative for Chinese text.
        n=len(json.dumps(payload,ensure_ascii=False))
        tokens=max(100,int(n*1.5)+250)
        return tokens*self.input_rate/1e6 + completion_tokens*self.output_rate/1e6
    def reserve(self,payload,completion_tokens=1800):
        estimate=self.estimate(payload,completion_tokens)
        if self.spent_estimate+estimate>self.budget+1e-9:
            raise BudgetError(f'预计本次额外费用 ${estimate:.4f} 超过剩余预算 ${max(0,self.budget-self.spent_estimate):.4f}；请调整预算或减少样本。')
        return estimate
    def json(self,system,user,completion_tokens=1800,allow_text_fallback=False):
        if not self.allow_upload:raise PermissionError('尚未授权向模型上传书评和划线内容')
        if not self.key:raise LLMError('需要配置模型 API Key')
        payload={'model':self.model,'messages':[{'role':'system','content':system},{'role':'user','content':json.dumps(user,ensure_ascii=False)}], 'response_format':{'type':'json_object'},'max_tokens':completion_tokens}
        projected=self.reserve(payload,completion_tokens)
        endpoint=self.base_url if self.base_url.endswith('/chat/completions') else self.base_url+'/chat/completions'
        req=urllib.request.Request(endpoint,data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=120) as res: raw=json.load(res)
        except urllib.error.HTTPError as e:
            # Do not echo bodies: external error payloads can contain sensitive context.
            raise LLMError(f'模型服务 HTTP {e.code}；请检查模型、密钥或余额') from e
        except (urllib.error.URLError,TimeoutError) as e:raise LLMError('模型网络请求失败') from e
        choice={};message={};content=None;usage={}
        try:
            choice=raw['choices'][0];message=choice['message'];content=message['content'];usage=raw.get('usage',{})
            value=json.loads(content)
        except (KeyError,ValueError,TypeError) as e:
            # Book chat can safely show a complete plain-text answer when the provider
            # ignores JSON mode. Citation IDs are still checked by chat_evidence.
            if (allow_text_fallback and isinstance(content,str) and content.strip()
                    and choice.get('finish_reason')=='stop' and not message.get('refusal')):
                value={'answer':content.strip(),'used_ids':[],'_plain_text_fallback':True}
            else:raise LLMError('模型未返回预期 JSON 格式') from e
        if not isinstance(value,dict):
            if (allow_text_fallback and isinstance(content,str) and content.strip()
                    and choice.get('finish_reason')=='stop' and not message.get('refusal')):
                value={'answer':content.strip(),'used_ids':[],'_plain_text_fallback':True}
            else:raise LLMError('模型未返回预期 JSON 格式')
        actual=(usage.get('prompt_tokens',0)*self.input_rate+usage.get('completion_tokens',0)*self.output_rate)/1e6 if usage else projected
        self.spent_estimate+=actual
        self.usage.append({'prompt_tokens':usage.get('prompt_tokens'),'completion_tokens':usage.get('completion_tokens'),'estimated_usd':round(actual,6),'rate_assumption':{'input_per_million':self.input_rate,'output_per_million':self.output_rate}})
        if self.spent_estimate>self.budget:raise BudgetError('本次请求之后估算累计费用已超过设置上限，停止后续请求；实际账单以供应商为准')
        return value
    def stats(self):return {'requests':len(self.usage),'estimated_usd':round(self.spent_estimate,6),'budget_usd':self.budget,'usage':self.usage}
