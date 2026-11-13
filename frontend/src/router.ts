import { createRouter,createWebHistory } from 'vue-router'
import { loadSession,session } from './api'
export const router=createRouter({history:createWebHistory(),routes:[
  {path:'/login',component:()=>import('./views/Auth.vue'),meta:{public:true}},
  {path:'/register',component:()=>import('./views/Auth.vue'),meta:{public:true}},
  {path:'/forgot-password',component:()=>import('./views/Auth.vue'),meta:{public:true}},
  {path:'/',component:()=>import('./views/Workspace.vue')},
  {path:'/employees',component:()=>import('./views/Workspace.vue'),meta:{manager:true}},
  {path:'/qualifications',component:()=>import('./views/Workspace.vue'),meta:{manager:true}},
  {path:'/demand-planning',component:()=>import('./views/Workspace.vue'),meta:{manager:true}},
  {path:'/availability',component:()=>import('./views/Workspace.vue')},
  {path:'/rules',component:()=>import('./views/Workspace.vue')},
  {path:'/scheduling',component:()=>import('./views/Workspace.vue'),meta:{manager:true}},
  {path:'/workbench',component:()=>import('./views/Workspace.vue'),meta:{manager:true}},
  {path:'/versions',component:()=>import('./views/Workspace.vue'),meta:{manager:true}},
  {path:'/my-schedule',component:()=>import('./views/Workspace.vue')},
  {path:'/leave',component:()=>import('./views/Workspace.vue'),meta:{module:'F09'}},
  {path:'/swaps',component:()=>import('./views/Workspace.vue'),meta:{module:'F10'}},
  {path:'/dynamic-adjustment',component:()=>import('./views/Workspace.vue'),meta:{manager:true,module:'F11'}},
  {path:'/ai-requirements',component:()=>import('./views/Workspace.vue'),meta:{employee:true,module:'F12'}},
  {path:'/ai-explanations',component:()=>import('./views/Workspace.vue'),meta:{module:'F13'}},
  {path:'/notifications',component:()=>import('./views/Workspace.vue'),meta:{module:'F14'}},
  {path:'/statistics',component:()=>import('./views/Workspace.vue'),meta:{module:'F15'}},
  {path:'/system-audit',component:()=>import('./views/Workspace.vue'),meta:{manager:true,module:'F16'}},
  {path:'/accounts',component:()=>import('./views/Workspace.vue'),meta:{manager:true}},
  {path:'/password-resets',component:()=>import('./views/Workspace.vue'),meta:{manager:true}},
  {path:'/profile',component:()=>import('./views/Workspace.vue')},
  {path:'/:pathMatch(.*)*',redirect:'/'}
]})
router.beforeEach(async to=>{if(to.meta.public)return true;if(!session.checked){try{await loadSession()}catch{return '/login'}}if(!session.user)return '/login';if(to.meta.manager && session.user.role!=='MANAGER')return '/';if(to.meta.employee && session.user.role!=='EMPLOYEE')return '/';return true})
