<template>
  <div class="page-container">
    <el-card shadow="never" class="head-card">
      <template #header>
        <div class="flex-between">
          <span class="page-title" style="margin: 0">
            {{ weekStatus.week_label || '本周周报' }}
            <el-tag size="small" :type="statusMeta.type" style="margin-left: 8px">
              {{ weekStatus.status_label }}
            </el-tag>
          </span>
          <div>
            <el-button :disabled="!weekStatus.can_generate" @click="onGenerate">
              <el-icon><MagicStick /></el-icon>
              {{ report && report.items.length ? '重新生成草稿' : '生成周报草稿' }}
            </el-button>
            <el-button @click="onSaveDraft" :loading="saving">保存草稿</el-button>
            <el-button type="primary" :disabled="!weekStatus.can_edit" @click="onSubmit">
              提交周报
            </el-button>
          </div>
        </div>
      </template>
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="截止提交">
          {{ formatDateTime(weekStatus.deadline_at) }}
        </el-descriptions-item>
        <el-descriptions-item label="定版时间">
          {{ formatDateTime(weekStatus.finalize_at) }}
        </el-descriptions-item>
        <el-descriptions-item label="提交状态">
          {{ weekStatus.submitted_at ? formatDateTime(weekStatus.submitted_at) : '未提交' }}
        </el-descriptions-item>
        <el-descriptions-item label="字数">
          {{ localCharCount }} 字
          <el-tag v-if="localCharCount < minChars" type="warning" size="small">
            低于 {{ minChars }} 字可能判定为无效周报
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>
      <el-alert
        v-if="report?.is_locked"
        type="warning"
        :closable="false"
        show-icon
        style="margin-top: 12px"
        title="本周周报已提交锁定，如需修改请提交修订并填写修改原因，修订记录会留痕。"
      />
    </el-card>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="17">
        <el-card
          v-for="section in REPORT_SECTIONS"
          :key="section.key"
          shadow="never"
          class="section-card"
        >
          <template #header>
            <div class="flex-between">
              <span class="section-title">
                <el-icon :color="section.color"><component :is="section.icon" /></el-icon>
                {{ section.label }}
              </span>
              <el-button text type="primary" @click="addItem(section.key)">
                <el-icon><Plus /></el-icon>
                添加一条
              </el-button>
            </div>
          </template>

          <div v-if="draft[section.key].length" class="item-list">
            <div v-for="(item, index) in draft[section.key]" :key="item._key" class="item-row">
              <el-input
                v-model="item.content"
                type="textarea"
                :rows="2"
                :placeholder="placeholderOf(section.key)"
                resize="vertical"
              />
              <div class="item-actions">
                <el-tag v-if="item.task_id" size="small" type="info">
                  来自任务：{{ item.task_title || `#${item.task_id}` }}
                </el-tag>
                <el-tag v-else size="small" effect="plain">手工填写</el-tag>
                <el-button
                  text
                  type="danger"
                  :icon="Delete"
                  @click="removeItem(section.key, index)"
                />
              </div>
            </div>
          </div>
          <el-empty v-else :description="`暂无${section.label}内容`" :image-size="60" />
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="7">
        <el-card shadow="never">
          <template #header>
            <span class="section-title">本周任务流水</span>
          </template>
          <el-alert
            type="info"
            :closable="false"
            title="周报草稿由「本周内的任务状态流水」自动生成，平时更新任务状态，周报就自动成型。"
          />
          <el-divider content-position="left">进行中</el-divider>
          <task-mini-list :tasks="weekTasks.in_progress" />
          <el-divider content-position="left">本周已完成</el-divider>
          <task-mini-list :tasks="weekTasks.done" />
          <el-divider content-position="left">阻塞中</el-divider>
          <task-mini-list :tasks="weekTasks.blocked" />
          <el-divider content-position="left">下周期到</el-divider>
          <task-mini-list :tasks="weekTasks.planned" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 修订原因弹窗 -->
    <el-dialog v-model="reasonVisible" title="提交修订" width="420px">
      <el-form>
        <el-form-item label="修改原因" required>
          <el-input v-model="reason" type="textarea" :rows="3" placeholder="如：补充本周遗漏的联调工作" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reasonVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="doSubmit">确认提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import { reportApi } from '@/api/reports'
import { taskApi } from '@/api/tasks'
import TaskMiniList from '@/components/TaskMiniList.vue'
import { REPORT_SECTIONS, REPORT_STATUS_MAP, formatDateTime } from '@/utils/dict'
import type { MyWeekStatus, ReportDetail, TaskItem } from '@/types'

type SectionKey = 'done' | 'progress' | 'risk' | 'plan'

interface DraftRow {
  _key: string
  content: string
  task_id: number | null
  task_title: string | null
  source: string
}

const loading = ref(false)
const saving = ref(false)
const submitting = ref(false)
const reasonVisible = ref(false)
const reason = ref('')
const report = ref<ReportDetail | null>(null)
const minChars = ref(20)

const weekStatus = ref<MyWeekStatus>({
  week_start: '',
  week_label: '',
  deadline_at: '-',
  finalize_at: '-',
  deadline_passed: false,
  has_report: false,
  report_id: null,
  status: 'draft',
  status_label: '未填写',
  submitted_at: null,
  can_edit: true,
  can_generate: true,
})

const weekTasks = reactive<Record<string, TaskItem[]>>({
  in_progress: [],
  done: [],
  blocked: [],
  planned: [],
})

const draft = reactive<Record<SectionKey, DraftRow[]>>({
  done: [],
  progress: [],
  risk: [],
  plan: [],
})

let seq = 0
const nextKey = () => `row-${++seq}`

const statusMeta = computed(() => REPORT_STATUS_MAP[weekStatus.value.status] ?? { type: 'info' })

const localCharCount = computed(() =>
  REPORT_SECTIONS.reduce(
    (sum, s) => sum + draft[s.key as SectionKey].reduce((n, row) => n + row.content.trim().length, 0),
    0,
  ),
)

const placeholders: Record<SectionKey, string> = {
  progress: '例：接口联调完成 70%，剩余异常分支待补；已同步测试同学准备用例',
  done: '例：完成周报生成算法开发与自测，共 5 个接口联调通过',
  plan: '例：完成灰度发布、补齐压力测试脚本，联调支付回调',
  risk: '例：缺少压测环境资源，需运维同学协助扩容 2 台机器',
}

function placeholderOf(key: SectionKey) {
  return placeholders[key]
}

function fillDraft(source: ReportDetail | null) {
  draft.done = []
  draft.progress = []
  draft.risk = []
  draft.plan = []
  if (!source) return
  const map: Record<string, SectionKey> = { done: 'done', progress: 'progress', risk: 'risk', plan: 'plan' }
  for (const item of source.items) {
    const key = map[item.section]
    if (!key) continue
    draft[key].push({
      _key: nextKey(),
      content: item.content,
      task_id: item.task_id,
      task_title: item.task_title,
      source: item.source,
    })
  }
}

function addItem(key: SectionKey) {
  draft[key].push({ _key: nextKey(), content: '', task_id: null, task_title: null, source: 'manual' })
}

function removeItem(key: SectionKey, index: number) {
  draft[key].splice(index, 1)
}

function collectItems() {
  const items: Array<{ section: string; content: string; task_id: number | null; source: string }> = []
  for (const section of REPORT_SECTIONS) {
    for (const row of draft[section.key as SectionKey]) {
      const content = row.content.trim()
      if (!content) continue
      items.push({
        section: section.key,
        content,
        task_id: row.task_id,
        source: row.task_id ? 'auto' : 'manual',
      })
    }
  }
  return items
}

async function loadReport() {
  loading.value = true
  try {
    const status = await reportApi.myWeekStatus()
    weekStatus.value = status
    if (status.has_report) {
      const detail = await reportApi.mineOfWeek(status.week_start)
      report.value = detail
      fillDraft(detail)
    } else {
      report.value = null
    }
  } finally {
    loading.value = false
  }
}

async function loadWeekTasks() {
  const [open, mine] = await Promise.all([
    taskApi.list({ participant_id: undefined, limit: 200 }).catch(() => [] as TaskItem[]),
    taskApi.mine(true).catch(() => [] as TaskItem[]),
  ])
  const pool = [...open, ...mine]
  const unique = new Map<number, TaskItem>()
  pool.forEach((t) => unique.set(t.id, t))
  const all = [...unique.values()]
  weekTasks.in_progress = all.filter((t) => t.status === 'in_progress').slice(0, 10)
  weekTasks.done = all.filter((t) => t.status === 'done').slice(0, 10)
  weekTasks.blocked = all.filter((t) => t.status === 'blocked').slice(0, 10)
  weekTasks.planned = all
    .filter((t) => t.status === 'todo' || t.status === 'in_progress')
    .filter((t) => !!t.due_date)
    .slice(0, 10)
}

async function onGenerate() {
  await ElMessageBox.confirm(
    '将按「本周完成任务 / 本周内有流水的任务 / 阻塞任务 / 下周到期的任务」自动汇总生成草稿。是否继续？',
    '生成周报草稿',
    { type: 'info' },
  ).catch(() => {
    throw new Error('cancel')
  })
  saving.value = true
  try {
    const detail = await reportApi.generate(true)
    report.value = detail
    fillDraft(detail)
    weekStatus.value = await reportApi.myWeekStatus()
    ElMessage.success('草稿已生成，请补充后提交')
  } finally {
    saving.value = false
  }
}

async function onSaveDraft() {
  saving.value = true
  try {
    await reportApi.saveDraft(collectItems())
    await loadReport()
    // 已提交的周报也允许暂存改动（后端会写修订留痕），故统一用同一句提示；
    // 修订流程本身由页面顶部的锁定提示条说明，此处不再重复打扰。
    ElMessage.success('草稿内容已保存，请及时「提交周报」')
  } finally {
    saving.value = false
  }
}

async function onSubmit() {
  if (!localCharCount.value) {
    ElMessage.warning('请至少填写一段内容')
    return
  }
  if (report.value?.submitted_at) {
    reasonVisible.value = true
    return
  }
  await ElMessageBox.confirm('提交后周报将被锁定，如需修改需走修订流程。确认提交？', '提交周报', {
    type: 'warning',
  }).catch(() => {
    throw new Error('cancel')
  })
  await doSubmit()
}

async function doSubmit() {
  submitting.value = true
  try {
    const detail = await reportApi.submit(collectItems(), undefined, reason.value)
    report.value = detail
    ElMessage.success('周报已提交')
    reasonVisible.value = false
    reason.value = ''
    await loadReport()
    await loadWeekTasks()
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await loadReport()
  await loadWeekTasks()
})
</script>

<style scoped>
.head-card {
  margin-bottom: 16px;
}

.section-card {
  margin-bottom: 16px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 15px;
  font-weight: 600;
  color: #16222f;
}

.item-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.item-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}
</style>
