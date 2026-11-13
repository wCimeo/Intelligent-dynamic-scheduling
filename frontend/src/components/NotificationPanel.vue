<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, session } from '../api'

const router = useRouter()
const isManager = computed(() => session.user?.role === 'MANAGER')
const busy = ref(false)
const error = ref('')
const notifications = ref<any[]>([])
const unread = ref(0)
const unreadOnly = ref(false)
const receipts = ref<any[]>([])
const periodOptions = ref<any[]>([])
const confirmationPeriodId = ref('')
const confirmation = ref<any>(null)
const pendingReceiptCount = computed(() => receipts.value.filter(item => item.status === 'PENDING').length)

const receiptStatuses: Record<string, string> = { PENDING: '待确认', CONFIRMED: '已确认' }
const categoryLabels: Record<string, string> = {
  SCHEDULE_PUBLISHED: '班表发布', LEAVE_REQUEST: '请假审批', LEAVE_RESULT: '请假结果',
  SWAP_REQUEST: '换班邀请', SWAP_RESPONSE: '换班回复', SWAP_RESULT: '换班结果'
}

function formatTime(value: string) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Shanghai' }).format(new Date(value))
}

async function loadNotifications() {
  const data = await api(`/me/notifications?unread_only=${unreadOnly.value}`)
  notifications.value = data.items
  unread.value = data.unread
}

async function loadEmployeeReceipts() {
  receipts.value = (await api('/me/publication-receipts')).items
}

async function loadConfirmation() {
  if (!confirmationPeriodId.value) { confirmation.value = null; return }
  try {
    confirmation.value = await api(`/periods/${confirmationPeriodId.value}/confirmation-status`)
  } catch (e: any) {
    confirmation.value = null
    if (e.status !== 404) error.value = e.message
  }
}

async function loadAll() {
  error.value = ''
  busy.value = true
  try {
    await loadNotifications()
    if (isManager.value) {
      periodOptions.value = (await api('/period-options')).items
      if (!confirmationPeriodId.value && periodOptions.value.length) confirmationPeriodId.value = periodOptions.value[0].id
      await loadConfirmation()
    } else {
      await loadEmployeeReceipts()
    }
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function openNotification(item: any) {
  try {
    if (!item.is_read) await api(`/me/notifications/${item.id}/read`, 'POST')
    if (item.target_url) await router.push(item.target_url)
    else await loadNotifications()
  } catch (e) {
    error.value = (e as Error).message
  }
}

async function markAllRead() {
  busy.value = true
  try {
    await api('/me/notifications/read-all', 'POST')
    await loadNotifications()
    ElMessage.success('全部通知已标记为已读')
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function confirmReceipt(item: any) {
  busy.value = true
  try {
    await api(`/me/publication-receipts/${item.id}/confirm`, 'POST', { expected_revision: item.revision })
    ElMessage.success('已确认为本人安排')
    await Promise.all([loadNotifications(), loadEmployeeReceipts()])
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

function changePeriod() {
  loadConfirmation().catch((e: any) => error.value = e.message)
}

onMounted(loadAll)
</script>

<template>
  <div class="page-heading">
    <div><span class="eyebrow">智能与数据 · F14</span><h1>通知与确认</h1><p class="muted">{{ isManager ? '查看业务通知，并跟踪员工对当前发布班表的确认进度。' : '查看班表、请假和换班通知，并确认已阅读当前发布版本。' }}</p></div>
    <el-badge :value="unread" :hidden="unread===0"><el-button :disabled="!unread" @click="markAllRead">全部已读</el-button></el-badge>
  </div>
  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="notification-error"/>

  <section class="panel notification-panel">
    <div class="section-heading"><h2>消息中心</h2><el-switch v-model="unreadOnly" active-text="只看未读" @change="loadNotifications"/></div>
    <div v-if="notifications.length" class="notification-list" v-loading="busy">
      <button v-for="item in notifications" :key="item.id" :class="['notification-item',{unread:!item.is_read}]" @click="openNotification(item)">
        <span class="notification-dot"></span>
        <div><div class="notification-title"><strong>{{ item.title }}</strong><el-tag size="small" effect="plain">{{ categoryLabels[item.category]||item.category }}</el-tag></div><p>{{ item.body }}</p><time>{{ formatTime(item.created_at) }}</time></div>
      </button>
    </div>
    <p v-else class="notification-empty">暂无通知。新的发布、请假或换班结果会自动出现在这里。</p>
  </section>

  <section v-if="isManager" class="panel confirmation-panel">
    <div class="section-heading"><h2>员工确认进度</h2><el-select v-model="confirmationPeriodId" class="period-select" placeholder="选择排班周" @change="changePeriod"><el-option v-for="period in periodOptions" :key="period.id" :label="`${period.week_start} 周一`" :value="period.id"/></el-select></div>
    <template v-if="confirmation">
      <div class="metric-grid"><div class="metric-card"><span>当前发布版本</span><strong>{{ confirmation.version_no }}</strong><small>版本号</small></div><div class="metric-card"><span>已确认</span><strong>{{ confirmation.counts.CONFIRMED }}</strong><small>受影响员工</small></div><div class="metric-card accent"><span>待确认</span><strong>{{ confirmation.counts.PENDING }}</strong><small>需要跟进</small></div></div>
      <el-table :data="confirmation.items" empty-text="当前版本没有需要重新确认的员工"><el-table-column prop="employee_no" label="员工编号" min-width="110"/><el-table-column prop="employee_name" label="姓名" min-width="110"/><el-table-column label="状态" min-width="100"><template #default="s"><el-tag :type="s.row.status==='CONFIRMED'?'success':'warning'" effect="light">{{ receiptStatuses[s.row.status] }}</el-tag></template></el-table-column><el-table-column label="确认时间" min-width="170"><template #default="s">{{ formatTime(s.row.confirmed_at) }}</template></el-table-column></el-table>
    </template>
    <p v-else class="muted">该周期尚无当前发布版本。</p>
  </section>

  <section v-else class="panel confirmation-panel">
    <div class="section-heading"><h2>我的班表确认</h2><el-tag type="warning" effect="light">{{ pendingReceiptCount }} 项待确认</el-tag></div>
    <el-table :data="receipts" empty-text="没有需要确认的新班表版本"><el-table-column label="排班周" min-width="140"><template #default="s">{{ s.row.week_start }} 周一</template></el-table-column><el-table-column label="发布版本" min-width="100"><template #default="s">第 {{ s.row.version_no }} 版</template></el-table-column><el-table-column label="状态" min-width="100"><template #default="s"><el-tag :type="s.row.status==='CONFIRMED'?'success':'warning'">{{ receiptStatuses[s.row.status] }}</el-tag></template></el-table-column><el-table-column label="确认时间" min-width="170"><template #default="s">{{ formatTime(s.row.confirmed_at) }}</template></el-table-column><el-table-column label="操作" min-width="110"><template #default="s"><el-button v-if="s.row.status==='PENDING'" link type="primary" :loading="busy" @click="confirmReceipt(s.row)">确认已阅</el-button><span v-else class="muted">已完成</span></template></el-table-column></el-table>
  </section>
</template>

<style scoped>
.notification-error{margin-bottom:18px}.notification-panel{margin-bottom:22px}.notification-list{display:grid;gap:2px}.notification-item{display:grid;grid-template-columns:10px 1fr;gap:12px;width:100%;border:0;border-bottom:1px solid #edf1f6;background:white;text-align:left;padding:15px 8px;cursor:pointer;color:inherit}.notification-item:hover{background:#f8fbff}.notification-item:last-child{border-bottom:0}.notification-dot{width:7px;height:7px;border-radius:50%;background:#d8e0ea;margin-top:8px}.notification-item.unread .notification-dot{background:#2563eb;box-shadow:0 0 0 4px #dbeafe}.notification-title{display:flex;align-items:center;gap:10px}.notification-title strong{font-size:14px}.notification-item p{color:#64748b;font-size:13px;line-height:1.7;margin:7px 0}.notification-item time{color:#9aa6b6;font-size:11px}.notification-empty{text-align:center;padding:36px;color:#8795a8}.period-select{width:190px}.confirmation-panel{margin-top:22px}
@media(max-width:760px){.period-select{width:150px}.notification-title{align-items:flex-start;flex-direction:column;gap:5px}}
</style>
