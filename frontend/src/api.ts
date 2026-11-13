import { reactive } from 'vue'
export interface User { id:string; name:string; username:string; role:string; status:string; revision:number; session_scope:string; must_change_password:boolean; review_note?:string }
export const session = reactive<{user:User|null;checked:boolean}>({user:null,checked:false})
let csrf = ''
export class ApiError extends Error { constructor(public status:number,public code:string,message:string){super(message)} }
export async function api<T=any>(path:string,method='GET',data?:unknown,key?:string):Promise<T>{
  if(method!=='GET' && !csrf){const res=await fetch('/api/v1/auth/csrf'); const body=await res.json(); if(!res.ok)throw new ApiError(res.status,body.code,body.message);csrf=body.data.token}
  let res:Response
  try {res=await fetch(path.startsWith('/api/')?path:'/api/v1'+path,{method,headers:{'Content-Type':'application/json',...(method!=='GET'?{'X-CSRF-Token':csrf}:{}),...(key?{'Idempotency-Key':key}:{})},...(data!==undefined?{body:JSON.stringify(data)}:{})})}
  catch{throw new Error('无法连接服务，请稍后重试')}
  const body=await res.json().catch(()=>({message:'服务暂不可用，请稍后重试',code:'UNAVAILABLE'}))
  if(!res.ok){if(body.code==='CSRF_FAILED')csrf='';throw new ApiError(res.status,body.code,body.message)}
  return body.data
}
export async function loadSession(){try{session.user=await api<User>('/auth/me')}catch(e){session.user=null;if(!(e instanceof ApiError && e.status===401))throw e}finally{session.checked=true}}
