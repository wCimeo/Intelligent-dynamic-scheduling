<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiError, api } from '../api'

type TimeWindow = { start_time: string; end_time: string }
type EditableOverride = {
  date: string
  mode: 'REPLACE' | 'BLOCK'
  windows: TimeWindow[]
  needs_confirmation?: boolean
  note?: string
}
type EditablePreference = {
  date: string
  template_id: string
  kind: 'PREFER' | 'AVOID'
  weight: number
  needs_confirmation?: boolean
  note?: string
}

const router = useRouter()
const text = ref('')
const parseResult = ref<any>(null)
const overrides = ref<EditableOverride[]>([])
const preferences = ref<EditablePreference[]>([])
const templates = ref<any[]>([])
const busy = ref(false)
const error = ref('')
const fallbackVisible = ref(false)
const reviewed = ref(false)
const finalResult = ref<any>(null)

const examples = [
  '下周三中午12点到13点有课，不能上班；周六希望能上早班。',
  '本周五下午要参加组会，14:00以后不能到岗。',
  '下周一全天不可用，下周二尽量安排晚班。'
]

const hasItems = computed(() => overrides.value.length > 0 || preferences.value.length > 0)
const needsAttention = computed(() => Boolean(
  (parseResult.value?.clarifications || []).length
  || overrides.value.some(item => item.needs_confirmation)
  || preferences.value.some(item => item.needs_confirmation)
))
const canConfirm = computed(() => (
  parseResult.value?.status === 'PENDING_CONFIRMATION'
  && hasItems.value
  && (!needsAttention.value || reviewed.value)
  && !busy.value
))

function localDate(offset = 0) {
  const value = new Date()
  value.setDate(value.getDate() + offset)
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 10)
}

function dateLabel(value: string) {
  if (!value) return '未选择日期'
  const day = new Date(`${value}T12:00:00`)
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'long', day: 'numeric', weekday: 'short', timeZone: 'Asia/Shanghai'
  }).format(day)
}

function templateName(item: EditablePreference) {
  return templates.value.find(template => String(template.id) === String(item.template_id))?.name || '请选择班次'
}

function initializeResult(data: any) {
  parseResult.value = data
  overrides.value = (data.overrides || []).map((item: any) => ({
    date: item.date,
    mode: item.mode,
    windows: (item.windows || []).map((window: any) => ({ ...window })),
    needs_confirmation: item.needs_confirmation,
    note: item.note || ''
  }))
  preferences.value = (data.preferences || []).map((item: any) => ({
    date: item.date,
    template_id: String(item.template_id),
    kind: item.kind,
    weight: Number(item.weight || 3),
    needs_confirmation: item.needs_confirmation,
    note: item.note || ''
  }))
  reviewed.value = false
  finalResult.value = null
}

async function parseText() {
  const value = text.value.trim()
  if (!value) {
    error.value = '请先描述你的时间或班次需求'
    return
  }
  error.value = ''
  fallbackVisible.value = false
  busy.value = true
  parseResult.value = null
  finalResult.value = null
  try {
    const data = await api('/me/ai/availability/parse', 'POST', { text: value })
    initializeResult(data)
    if (!data.overrides?.length && !data.preferences?.length) {
      error.value = '模型没有识别出可确认的日期例外或班次偏好，请补充具体日期和时段。'
    }
  } catch (e) {
    fallbackVisible.value = true
    if (e instanceof ApiError && e.code === 'AI_USER_LIMIT') {
      error.value = '今日智能解析次数已用完，可直接使用手工时间填报。'
    } else if (e instanceof ApiError && e.code === 'AI_GLOBAL_LIMIT') {
      error.value = '今日系统智能调用额度已用完，可直接使用手工时间填报。'
    } else {
      error.value = `${(e as Error).message}。本次结果没有写入任何时间或偏好。`
    }
  } finally {
    busy.value = false
  }
}

function addOverride() {
  overrides.value.push({
    date: localDate(1),
    mode: 'BLOCK',
    windows: [{ start_time: '12:00', end_time: '13:00' }],
    needs_confirmation: false,
    note: ''
  })
}

function removeOverride(index: number) {
  overrides.value.splice(index, 1)
}

function addWindow(item: EditableOverride) {
  item.windows.push({ start_time: '12:00', end_time: '13:00' })
}

function removeWindow(item: EditableOverride, index: number) {
  item.windows.splice(index, 1)
}

function addPreference() {
  const firstTemplate = templates.value[0]
  preferences.value.push({
    date: localDate(1),
    template_id: firstTemplate ? String(firstTemplate.id) : '',
    kind: 'PREFER',
    weight: 3,
    needs_confirmation: false,
    note: ''
  })
}

function removePreference(index: number) {
  preferences.value.splice(index, 1)
}

function validateEditableItems() {
  for (const item of overrides.value) {
    if (!item.date) return '每个日期例外都需要选择具体日期'
    if (item.mode === 'BLOCK' && !item.windows.length) return `${dateLabel(item.date)}需要至少一个不可用时段`
    for (const window of item.windows) {
      if (!window.start_time || !window.end_time) return `${dateLabel(item.date)}存在未填写完整的时段`
      if (window.end_time <= window.start_time) return `${dateLabel(item.date)}的结束时间必须晚于开始时间`
    }
  }
  const overrideDates = overrides.value.map(item => item.date)
  if (new Set(overrideDates).size !== overrideDates.length) return '同一天不能设置多个日期例外'
  for (const item of preferences.value) {
    if (!item.date) return '每条偏好都需要选择具体日期'
    if (!item.template_id) return '每条偏好都需要选择班次'
  }
  const keys = preferences.value.map(item => `${item.date}:${item.template_id}`)
  if (new Set(keys).size !== keys.length) return '同一天同一班次只能设置一个偏好'
  return ''
}

async function confirmResult() {
  if (!canConfirm.value) return
  const validation = validateEditableItems()
  if (validation) {
    error.value = validation
    return
  }
  error.value = ''
  busy.value = true
  try {
    finalResult.value = await api(
      `/me/ai/availability/parses/${parseResult.value.id}/confirm`,
      'POST',
      {
        expected_revision: parseResult.value.revision,
        overrides: overrides.value.map(item => ({
          date: item.date,
          mode: item.mode,
          windows: item.windows.map(window => ({
            start_time: window.start_time,
            end_time: window.end_time
          }))
        })),
        preferences: preferences.value.map(item => ({
          date: item.date,
          template_id: Number(item.template_id),
          kind: item.kind,
          weight: Number(item.weight)
        }))
      }
    )
    parseResult.value.status = 'CONFIRMED'
    ElMessage.success('已写入日期例外和偏好草稿')
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function rejectResult() {
  try {
    await ElMessageBox.confirm(
      '放弃后不会把本次识别结果写入可用时间或偏好。',
      '放弃这次解析结果？',
      { confirmButtonText: '确认放弃', cancelButtonText: '继续核对', type: 'warning' }
    )
  } catch {
    return
  }
  error.value = ''
  busy.value = true
  try {
    await api(
      `/me/ai/availability/parses/${parseResult.value.id}/reject`,
      'POST',
      { expected_revision: parseResult.value.revision }
    )
    parseResult.value.status = 'REJECTED'
    ElMessage.success('本次解析结果已放弃，没有写入业务数据')
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

function startAnother() {
  parseResult.value = null
  finalResult.value = null
  overrides.value = []
  preferences.value = []
  reviewed.value = false
  error.value = ''
  fallbackVisible.value = false
  text.value = ''
}

function useExample(example: string) {
  text.value = example
  parseResult.value = null
  finalResult.value = null
  error.value = ''
}

onMounted(async () => {
  try {
    templates.value = (await api('/shift-template-options')).items
  } catch (e) {
    error.value = `班次选项加载失败：${(e as Error).message}`
  }
})
</script>

<template>
  <div class="page-heading">
    <div>
      <span class="eyebrow">智能助手 · F12</span>
      <h1>智能需求录入</h1>
      <p class="muted">用自然语言描述不能到岗的日期或班次偏好。AI 只生成待确认草稿，核对并确认后才会写入。</p>
    </div>
    <el-tag type="info" effect="plain">仅限本人数据</el-tag>
  </div>

  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="ai-alert"/>

  <section class="panel ai-input-panel">
    <div class="section-heading">
      <div>
        <h2>描述你的需求</h2>
        <p class="muted">请尽量写出具体日期、时间和“不能上班”或“更喜欢”的含义。</p>
      </div>
      <span class="privacy-note">原始描述保存在解析记录中，不写入班表备注</span>
    </div>
    <el-input
      v-model="text"
      type="textarea"
      :rows="5"
      maxlength="2000"
      show-word-limit
      resize="vertical"
      placeholder="例如：下周三中午12点到13点有课，不能上班；周六希望能上早班。"
      @keydown.ctrl.enter="parseText"
    />
    <div class="ai-input-actions">
      <div class="example-list">
        <span class="muted">示例：</span>
        <el-button v-for="example in examples" :key="example" link type="primary" @click="useExample(example)">
          {{ example.slice(0, 12) }}…
        </el-button>
      </div>
      <el-button type="primary" :loading="busy" :disabled="!text.trim()" @click="parseText">
        解析并预览
      </el-button>
    </div>
    <div class="ai-safety-note">
      <span>不会直接修改班表</span>
      <span>不确定内容会单独提示</span>
      <span>随时可放弃结果</span>
    </div>
  </section>

  <section v-if="fallbackVisible" class="panel fallback-panel">
    <div>
      <h2>先手工填写也可以</h2>
      <p class="muted">模型服务不可用时，原有可用时间与偏好页面不受影响。</p>
    </div>
    <el-button type="primary" plain @click="router.push('/availability')">前往时间与偏好</el-button>
  </section>

  <template v-if="parseResult">
    <section class="parse-overview">
      <article class="panel source-card">
        <span class="eyebrow">原始描述</span>
        <p>{{ text.trim() }}</p>
      </article>
      <article class="panel summary-card">
        <div class="summary-heading">
          <span class="eyebrow">AI 结构化摘要</span>
          <el-tag :type="parseResult.status === 'PENDING_CONFIRMATION' ? 'warning' : parseResult.status === 'CONFIRMED' ? 'success' : 'info'" effect="light">
            {{ parseResult.status === 'PENDING_CONFIRMATION' ? '待确认' : parseResult.status === 'CONFIRMED' ? '已确认' : '已放弃' }}
          </el-tag>
        </div>
        <h2>{{ parseResult.summary }}</h2>
        <div class="usage-line">
          <span>模型 {{ parseResult.model }}</span>
          <span v-if="parseResult.usage?.total_tokens">本次约 {{ parseResult.usage.total_tokens }} tokens</span>
          <span>仅作时间与偏好草稿，不生成班表</span>
        </div>
      </article>
    </section>

    <el-alert
      v-if="(parseResult.clarifications || []).length"
      title="以下内容需要你核对"
      type="warning"
      :closable="false"
      show-icon
      class="ai-alert"
    >
      <ul class="clarification-list">
        <li v-for="item in parseResult.clarifications" :key="item">{{ item }}</li>
      </ul>
    </el-alert>

    <div v-if="parseResult.status === 'PENDING_CONFIRMATION'" class="editor-grid">
      <section class="panel structured-panel">
        <div class="section-heading">
          <div>
            <h2>日期例外</h2>
            <p class="muted">“扣除”表示在常规可用时间中减去一段；“替换”表示当天只保留列出的可用时段，留空即全天不可用。</p>
          </div>
          <el-button size="small" @click="addOverride">添加日期例外</el-button>
        </div>
        <div v-if="!overrides.length" class="empty-structure">没有识别到日期例外</div>
        <article v-for="(item, index) in overrides" :key="`override-${index}`" class="structured-item">
          <div class="item-toolbar">
            <div class="date-title">
              <strong>{{ dateLabel(item.date) }}</strong>
              <el-tag v-if="item.needs_confirmation" size="small" type="warning" effect="plain">需核对</el-tag>
            </div>
            <el-button link type="danger" @click="removeOverride(index)">移除</el-button>
          </div>
          <div class="item-fields">
            <el-date-picker v-model="item.date" type="date" value-format="YYYY-MM-DD" :clearable="false" />
            <el-select v-model="item.mode">
              <el-option label="扣除不可用时段" value="BLOCK"/>
              <el-option label="替换当天可用时段" value="REPLACE"/>
            </el-select>
            <el-button size="small" @click="addWindow(item)">添加时段</el-button>
          </div>
          <p class="mode-hint">
            {{ item.mode === 'BLOCK' ? '下列时段不能上班；当天其他常规可用时间保持不变。' : item.windows.length ? '下列时段是当天唯一可上班时间。' : '未填写时段，表示当天全天不可用。' }}
          </p>
          <div v-for="(window, windowIndex) in item.windows" :key="`window-${windowIndex}`" class="time-row">
            <el-time-select v-model="window.start_time" start="00:00" step="00:15" end="23:45" placeholder="开始"/>
            <span>至</span>
            <el-time-select v-model="window.end_time" start="00:15" step="00:15" end="23:59" placeholder="结束"/>
            <el-button link type="danger" @click="removeWindow(item, windowIndex)">删除</el-button>
          </div>
          <p v-if="item.note" class="item-note">AI 备注：{{ item.note }}</p>
        </article>
      </section>

      <section class="panel structured-panel">
        <div class="section-heading">
          <div>
            <h2>班次偏好</h2>
            <p class="muted">偏好只影响优化建议，不代表不能上班。不能上班请写入左侧日期例外。</p>
          </div>
          <el-button size="small" @click="addPreference">添加偏好</el-button>
        </div>
        <div v-if="!preferences.length" class="empty-structure">没有识别到班次偏好</div>
        <article v-for="(item, index) in preferences" :key="`preference-${index}`" class="structured-item">
          <div class="item-toolbar">
            <div class="date-title">
              <strong>{{ dateLabel(item.date) }} · {{ templateName(item) }}</strong>
              <el-tag v-if="item.needs_confirmation" size="small" type="warning" effect="plain">需核对</el-tag>
            </div>
            <el-button link type="danger" @click="removePreference(index)">移除</el-button>
          </div>
          <div class="preference-fields">
            <el-date-picker v-model="item.date" type="date" value-format="YYYY-MM-DD" :clearable="false"/>
            <el-select v-model="item.template_id" placeholder="选择班次">
              <el-option v-for="template in templates" :key="template.id" :label="`${template.name} ${template.start_time}—${template.end_time}`" :value="String(template.id)"/>
            </el-select>
            <el-select v-model="item.kind">
              <el-option label="希望安排" value="PREFER"/>
              <el-option label="尽量避开" value="AVOID"/>
            </el-select>
            <el-select v-model="item.weight">
              <el-option v-for="weight in 5" :key="weight" :label="`强度 ${weight}`" :value="weight"/>
            </el-select>
          </div>
          <p v-if="item.note" class="item-note">AI 备注：{{ item.note }}</p>
        </article>
      </section>
    </div>

    <section v-if="parseResult.status === 'PENDING_CONFIRMATION'" class="panel confirm-panel">
      <div>
        <h2>确认后写入</h2>
        <p class="muted">日期例外立即生效于未来时间；班次偏好保存为草稿，仍需在“时间与偏好”页面提交。</p>
        <el-checkbox v-if="needsAttention" v-model="reviewed">我已核对提示和需确认条目</el-checkbox>
      </div>
      <div class="confirm-actions">
        <el-button :disabled="busy" @click="rejectResult">放弃结果</el-button>
        <el-button type="primary" :disabled="!canConfirm" :loading="busy" @click="confirmResult">确认并写入</el-button>
      </div>
    </section>

    <section v-else-if="parseResult.status === 'CONFIRMED'" class="panel success-panel">
      <div class="success-mark">✓</div>
      <div>
        <h2>结果已写入</h2>
        <p class="muted">
          已保存 {{ finalResult?.override_count || 0 }} 条日期例外和
          {{ finalResult?.preference_count || 0 }} 条偏好草稿。偏好可继续核对后在时间与偏好页面提交。
        </p>
      </div>
      <div class="success-actions">
        <el-button @click="startAnother">继续录入</el-button>
        <el-button type="primary" @click="router.push('/availability')">查看时间与偏好</el-button>
      </div>
    </section>

    <section v-else class="panel rejected-panel">
      <div>
        <h2>本次结果已放弃</h2>
        <p class="muted">可用时间和偏好没有发生任何变化。</p>
      </div>
      <el-button type="primary" plain @click="startAnother">重新描述</el-button>
    </section>
  </template>

  <section v-else class="panel ai-guide">
    <div class="guide-step"><span>1</span><div><strong>描述具体需求</strong><p>写出日期、时间和原因性质。</p></div></div>
    <div class="guide-step"><span>2</span><div><strong>核对结构化结果</strong><p>模型可能误解，重要安排以你的确认为准。</p></div></div>
    <div class="guide-step"><span>3</span><div><strong>确认后才写入</strong><p>日期例外直接保存，偏好先成为草稿。</p></div></div>
  </section>
</template>

<style scoped>
.ai-alert{margin-bottom:18px}.ai-input-panel{margin-bottom:22px}.ai-input-panel .section-heading{align-items:flex-start}.ai-input-panel .section-heading p{margin:5px 0 0}.privacy-note{color:#94a3b8;font-size:11px}.ai-input-actions{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:14px}.example-list{display:flex;align-items:center;gap:2px;flex-wrap:wrap}.ai-safety-note{display:flex;gap:24px;color:#64748b;font-size:11px;border-top:1px solid #edf1f6;margin-top:16px;padding-top:12px}.ai-safety-note span::before{content:'✓';color:#16a34a;margin-right:6px;font-weight:700}.fallback-panel,.confirm-panel,.success-panel,.rejected-panel{display:flex;align-items:center;justify-content:space-between;gap:22px;margin-bottom:22px}.fallback-panel h2,.confirm-panel h2,.success-panel h2,.rejected-panel h2{font-size:17px;margin-bottom:5px}.fallback-panel p,.confirm-panel p,.success-panel p,.rejected-panel p{margin:0}.parse-overview{display:grid;grid-template-columns:.8fr 1.2fr;gap:18px;margin-bottom:18px}.source-card p{white-space:pre-wrap;margin:0;color:#475569;line-height:1.8}.summary-card{background:linear-gradient(125deg,#f1f6ff,#fff)}.summary-heading{display:flex;align-items:center;justify-content:space-between}.summary-card h2{font-size:20px;margin:4px 0 12px}.usage-line{display:flex;gap:16px;flex-wrap:wrap;color:#8491a5;font-size:11px}.clarification-list{margin:6px 0 0;padding-left:18px;line-height:1.8}.editor-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:22px}.structured-panel{min-width:0}.structured-panel .section-heading{align-items:flex-start}.structured-panel .section-heading p{margin:5px 0 0;max-width:520px}.structured-panel .section-heading .el-button{flex:none}.structured-item{background:#f8fafc;border:1px solid #e8eef6;border-radius:10px;padding:14px;margin-top:12px}.item-toolbar,.date-title{display:flex;align-items:center;gap:8px}.item-toolbar{justify-content:space-between;margin-bottom:12px}.item-fields,.preference-fields{display:grid;gap:8px;align-items:center}.item-fields{grid-template-columns:1fr 1fr auto}.preference-fields{grid-template-columns:1fr 1.4fr .8fr .7fr}.item-fields :deep(.el-date-editor),.item-fields :deep(.el-select),.preference-fields :deep(.el-date-editor),.preference-fields :deep(.el-select){width:100%}.mode-hint{margin:10px 0 8px;color:#8491a5;font-size:11px;line-height:1.6}.time-row{display:grid;grid-template-columns:1fr auto 1fr auto;gap:7px;align-items:center;margin-top:7px}.time-row :deep(.el-select){width:100%}.item-note{margin:10px 0 0;padding-top:9px;border-top:1px solid #edf1f6;color:#94a3b8;font-size:11px;line-height:1.6}.empty-structure{text-align:center;color:#94a3b8;font-size:12px;padding:28px 10px;border:1px dashed #dbe4f0;border-radius:9px}.confirm-panel{background:linear-gradient(120deg,#f8fbff,#fff)}.confirm-actions,.success-actions{display:flex;gap:8px;flex:none}.success-panel{border-color:#bbf7d0;background:#f0fdf4}.success-mark{width:48px;height:48px;border-radius:50%;background:#16a34a;color:white;display:grid;place-items:center;font-size:24px;flex:none}.success-panel .muted{flex:1}.rejected-panel{background:#f8fafc}.ai-guide{display:grid;grid-template-columns:repeat(3,1fr);gap:24px;margin-top:8px}.guide-step{display:flex;gap:12px}.guide-step>span{width:28px;height:28px;border-radius:50%;background:#eff6ff;color:#2563eb;display:grid;place-items:center;font-size:12px;font-weight:700;flex:none}.guide-step strong{font-size:13px}.guide-step p{margin:5px 0 0;color:#8491a5;font-size:11px;line-height:1.7}
@media(max-width:1100px){.editor-grid{grid-template-columns:1fr}.parse-overview{grid-template-columns:1fr}.preference-fields{grid-template-columns:1fr 1fr}.ai-guide{grid-template-columns:1fr}.ai-guide{gap:16px}}
@media(max-width:700px){.page-heading{align-items:flex-start}.ai-input-actions,.fallback-panel,.confirm-panel,.success-panel,.rejected-panel{align-items:stretch;flex-direction:column}.ai-safety-note{gap:8px;flex-direction:column}.item-fields,.preference-fields{grid-template-columns:1fr}.time-row{grid-template-columns:1fr 1fr}.time-row span{display:none}.confirm-actions,.success-actions{width:100%;flex-wrap:wrap}.privacy-note{display:none}}
</style>
