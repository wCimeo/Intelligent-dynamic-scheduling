<script setup lang="ts">
import { computed,reactive,ref } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { Calendar,ArrowRight,Lock,User,Check } from '@element-plus/icons-vue'
import { api,session } from '../api'
const route=useRoute(),router=useRouter()
const mode=computed(()=>route.path==='/register'?'register':route.path==='/forgot-password'?'forgot':'login')
const title=computed(()=>({login:'欢迎回来',register:'创建员工账号',forgot:'找回密码'}[mode.value]))
const form=reactive({username:'',name:'',password:'',password_confirmation:''})
const busy=ref(false),error=ref(''),notice=ref('')
async function submit(){error.value='';notice.value='';busy.value=true;try{
  if(mode.value==='login'){session.user=await api('/auth/login','POST',{username:form.username,password:form.password});session.checked=true;await router.push('/')}
  else if(mode.value==='register'){await api('/auth/register','POST',form);notice.value='注册成功。管理员审核后即可使用，请稍后登录查看审核状态。';form.password='';form.password_confirmation=''}
  else{await api('/auth/password-reset-requests','POST',{username:form.username});notice.value='如账号有效，管理员将核实并协助处理。请联系门店管理员。'}
}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
</script>
<template>
<div class="auth-page">
  <a class="brand auth-brand" href="/login"><span class="brand-icon"><el-icon><Calendar /></el-icon></span><span>智能排班<small>让团队协作，更从容</small></span></a>
  <main class="auth-layout">
    <section class="auth-intro"><span class="eyebrow">团队协作 · 有序安排</span><h1>把合适的人，<br>安排在合适的时间。</h1><p>统筹人员、岗位与时间，让每一次排班<br>都有依据，让每一次调整清晰可见。</p>
    <div class="illustration" aria-hidden="true"><div class="illustration-top"><strong>一周安排，一目了然</strong><span class="mini-dot"></span></div><div class="week-labels"><span v-for="d in ['周一','周二','周三','周四','周五']">{{d}}</span></div><div class="week-art"><div v-for="i in 15" :class="['art-cell','shade-'+i%4]"><i></i><b></b></div></div><div class="art-note"><el-icon><Check /></el-icon> 清晰的安排，从这里开始</div></div>
    </section>
    <section class="auth-card"><span class="small-label">智能排班与动态调班系统</span><h2>{{title}}</h2><p class="muted">{{mode==='login'?'登录你的账号，开始今天的工作':mode==='register'?'提交注册后，由管理员审核启用':'提交申请后，请联系管理员核实身份'}}</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="feedback"/>
    <el-alert v-if="notice" :title="notice" type="success" :closable="false" show-icon class="feedback"/>
    <el-form label-position="top" @submit.prevent="submit">
      <el-form-item label="账号"><el-input v-model="form.username" :prefix-icon="User" placeholder="请输入账号" autocomplete="username" maxlength="32" size="large" required /></el-form-item>
      <el-form-item v-if="mode==='register'" label="姓名"><el-input v-model="form.name" placeholder="请输入真实姓名" maxlength="64" size="large" required /></el-form-item>
      <el-form-item v-if="mode!=='forgot'" label="密码"><el-input v-model="form.password" :prefix-icon="Lock" type="password" show-password :autocomplete="mode==='login'?'current-password':'new-password'" :placeholder="mode==='register'?'12—128 个字符':'请输入密码'" maxlength="128" size="large" required /></el-form-item>
      <el-form-item v-if="mode==='register'" label="确认密码"><el-input v-model="form.password_confirmation" type="password" show-password autocomplete="new-password" placeholder="请再次输入密码" maxlength="128" size="large" required /></el-form-item>
      <div v-if="mode==='login'" class="form-link"><router-link to="/forgot-password">忘记密码？</router-link></div>
      <el-button type="primary" size="large" native-type="submit" :loading="busy" class="full-button">{{mode==='login'?'登 录':mode==='register'?'提交注册':'提交重置申请'}}<el-icon class="button-arrow"><ArrowRight /></el-icon></el-button>
    </el-form>
    <div class="auth-switch"><template v-if="mode==='login'">还没有账号？<router-link to="/register">注册员工账号</router-link></template><router-link v-else to="/login">返回登录</router-link></div>
    <p class="auth-footnote"><el-icon><Lock /></el-icon> 账号信息仅用于本门店的排班与协作</p>
    </section>
  </main><footer class="auth-footer">清晰安排 · 从容协作</footer>
</div>
</template>
