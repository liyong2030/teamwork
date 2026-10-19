<template>
  <div class="page-container" v-loading="loading">
    <div class="page-card">
      <div class="flex-between">
        <div>
          <span class="page-title" style="margin: 0">{{ project?.name || '项目详情' }}</span>
          <el-tag size="small" style="margin-left: 8px">{{ project?.code }}</el-tag>
          <span class="muted" style="margin-left: 10px">
            负责人：{{ project?.owner_name || '未指派' }} ·
            {{ project?.department_name || '无归属部门' }}
          </span>
        </div>
        <div>
          <el-button @click="router.push({ name: 'project-list' })">返回列表</el-button>
          <el-button type="primary" @click="openCreate">
            <el-icon><Plus /></el-icon>
            新建任务
          </el-button>
        </div>
      </div>
    </div>

    <div class="board">
      <div v-for="col in columns" :key="col.status" class="board-col">
        <div class="col-head">
          <span class="col-title">
            <span class="dot" :style="{ background: TASK_STATUS_MAP[col.status]?.color }" />
            {{ col.title }}
          </span>
          <el-tag size="small">{{ col.tasks.length }}</el-tag>
        </div>
        <div class="col-body" @dragover.prevent="onDragOver" @drop="onDrop(col.status)">
          <div
            v-for="task in col.tasks"
            :key="task.id"
            class="task-card"
            :class="{ 'is-overdue': task.is_overdue }"
            draggable="true"
            @dragstart="onDragStart(task)"
            @click="openDetail(task)"
          >
            <div class="task-card-title">{{ task.title }}</div>
            <div class="task-card-meta">
              <el-tag size="small" :type="TASK_PRIORITY_MAP[task.priority]?.type">
                {{ task.priority }}
              </el-tag>
              <span>{{ task.owner_name || '未指派' }}</span>
              <span v-if="task.due_date" :class="{ 'text-danger': task.is_overdue }">
                {{ task.due_date }}
              </span>
            </div>
            <el-progress
              v-if="task.status === 'in_progress'"
              :percentage="task.progress"
              :stroke-width="5"
              :show-text="false"
            />
          </div>
          <el-empty v-if="!col.tasks.length" description="拖动任务到此列" :image-size="50" />
        </div>
      </div>
    </div>

    <el-drawer :model-value="drawerVisible" :title="form.title || '任务'" size="560px" @close="drawerVisible = false">
      <el-tabs>
        <el-tab-pane label="基本信息">
          <el-form label-width="88px">
            <el-form-item label="标题" required>
              <el-input v-model="form.title" />
            </el-form-item>
            <el-form-item label="负责人">
              <el-select v-model="form.owner_id" filterable clearable style="width: 100%">
                <el-option
                  v-for="m in members"
                  :key="m.id"
                  :label="m.full_name"
                  :value="m.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="协作人">
              <el-select v-model="form.collaborator_ids" multiple filterable style="width: 100%">
                <el-option v-for="m in members" :key="m.id" :label="m.full_name" :value="m.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="优先级">
              <el-select v-model="form.priority">
                <el-option
                  v-for="(v, k) in TASK_PRIORITY_MAP"
                  :key="k"
                  :label="v.label"
                  :value="k"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="起止日期">
              <el-date-picker
                v-model="range"
                type="daterange"
                value-format="YYYY-MM-DD"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="预估工时">
              <el-input-number v-model="form.estimated_hours" :min="0" :step="1" />
            </el-form-item>
            <el-form-item label="实际工时">
              <el-input-number v-model="form.actual_hours" :min="0" :step="1" />
            </el-form-item>
            <el-form-item label="描述">
              <el-input v-model="form.description" type="textarea" :rows="3" />
            </el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="检查清单" v-if="currentId">
          <div v-for="(item, idx) in checklist" :key="idx" class="check-row">
            <el-checkbox
              :model-value="item.done"
              @change="(checked: boolean | string | number) => onToggleCheck(idx, !!checked)"
            >
              <span :class="{ 'line-through': item.done }">{{ item.text }}</span>
            </el-checkbox>
          </div>
          <div class="check-add">
            <el-input v-model="newCheck" size="small" placeholder="新增检查项" />
            <el-button size="small" type="primary" @click="addCheck">添加</el-button>
          </div>
        </el-tab-pane>
        <el-tab-pane label="状态流转" v-if="currentId">
          <el-form :inline="true">
            <el-form-item label="目标状态">
              <el-select v-model="targetStatus" style="width: 140px">
                <el-option
                  v-for="(v, k) in TASK_STATUS_MAP"
                  :key="k"
                  :label="v.label"
                  :value="k"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="进度">
              <el-input-number v-model="targetProgress" :min="0" :max="100" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="statusSaving" @click="submitStatus">
                保存流转
              </el-button>
            </el-form-item>
          </el-form>
          <el-divider content-position="left">流水记录</el-divider>
          <el-timeline>
            <el-timeline-item
              v-for="log in logs"
              :key="log.id"
              :timestamp="formatDateTime(log.created_at)"
            >
              {{ TASK_STATUS_MAP[log.from_status ?? '']?.label || '新建' }} →
              {{ TASK_STATUS_MAP[log.to_status]?.label }} · {{ log.operator_name }}
            </el-timeline-item>
          </el-timeline>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="drawerVisible = false">关闭</el-button>
        <el-button v-if="currentId" type="danger" text @click="doCancel">取消任务</el-button>
        <el-button type="primary" :loading="saving" @click="saveTask">
          {{ currentId ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { projectApi } from '@/api/projects'
import { taskApi } from '@/api/tasks'
import { TASK_PRIORITY_MAP, TASK_STATUS_MAP, formatDateTime } from '@/utils/dict'
import type { BoardColumn, ChecklistEntry, MemberOption, ProjectItem, TaskItem, TaskLogItem } from '@/types'

const route = useRoute()
const router = useRouter()

const projectId = computed(() => Number(route.params.id))
const loading = ref(false)
const drawerVisible = ref(false)
const saving = ref(false)
const statusSaving = ref(false)
const currentId = ref<number | null>(null)
const project = ref<ProjectItem | null>(null)
const board = ref<BoardColumn[]>([])
const logs = ref<TaskLogItem[]>([])
const members = ref<MemberOption[]>([])
const checklist = ref<ChecklistEntry[]>([])
const newCheck = ref('')
const range = ref<[string, string] | null>(null)

const form = ref({
  title: '',
  owner_id: undefined as number | undefined,
  collaborator_ids: [] as number[],
  priority: 'p2',
  description: '',
  estimated_hours: undefined as number | undefined,
  actual_hours: undefined as number | undefined,
})

const targetStatus = ref('in_progress')
const targetProgress = ref(0)

const columns = computed(() =>
  ['todo', 'in_progress', 'blocked', 'done', 'cancelled'].map((status) => {
    const found = board.value.find((c) => c.status === status)
    return {
      status,
      title: TASK_STATUS_MAP[status]?.label ?? status,
      tasks: found?.tasks ?? [],
    }
  }),
)

let dragging: TaskItem | null = null

function onDragStart(task: TaskItem) {
  dragging = task
}

function onDragOver() {
  /* HTML5 拖放必须阻止默认行为，否则不会触发 drop；此处无需额外处理 */
}

async function onDrop(toStatus: string) {
  if (!dragging || dragging.status === toStatus) {
    dragging = null
    return
  }
  const task = dragging
  dragging = null
  try {
    await taskApi.move(task.id, toStatus)
    ElMessage.success('任务已移动')
    await loadBoard()
  } catch {
    await loadBoard()
  }
}

async function loadBoard() {
  loading.value = true
  try {
    const [p, cols] = await Promise.all([
      projectApi.detail(projectId.value),
      projectApi.board(projectId.value),
    ])
    project.value = p
    board.value = cols
  } finally {
    loading.value = false
  }
}

function openCreate() {
  currentId.value = null
  form.value = {
    title: '',
    owner_id: undefined,
    collaborator_ids: [],
    priority: 'p2',
    description: '',
    estimated_hours: undefined,
    actual_hours: undefined,
  }
  range.value = null
  checklist.value = []
  logs.value = []
  drawerVisible.value = true
}

async function openDetail(task: TaskItem) {
  currentId.value = task.id
  const full = await taskApi.detail(task.id)
  form.value = {
    title: full.title,
    owner_id: full.owner_id ?? undefined,
    collaborator_ids: full.collaborator_ids,
    priority: full.priority,
    description: full.description ?? '',
    estimated_hours: full.estimated_hours ?? undefined,
    actual_hours: full.actual_hours ?? undefined,
  }
  range.value = full.start_date && full.due_date ? [full.start_date, full.due_date] : null
  checklist.value = full.checklist ?? []
  targetStatus.value = full.status
  targetProgress.value = full.progress
  logs.value = await taskApi.logs(task.id)
  drawerVisible.value = true
}

async function saveTask() {
  if (!form.value.title.trim()) {
    ElMessage.warning('请填写任务标题')
    return
  }
  saving.value = true
  try {
    const payload = {
      title: form.value.title,
      project_id: projectId.value,
      owner_id: form.value.owner_id ?? null,
      collaborator_ids: form.value.collaborator_ids,
      priority: form.value.priority,
      description: form.value.description || null,
      estimated_hours: form.value.estimated_hours ?? null,
      actual_hours: form.value.actual_hours ?? null,
      start_date: range.value?.[0] ?? null,
      due_date: range.value?.[1] ?? null,
    }
    if (currentId.value) {
      await taskApi.update(currentId.value, payload)
      ElMessage.success('已保存')
    } else {
      await taskApi.create(payload)
      ElMessage.success('已创建')
    }
    drawerVisible.value = false
    await loadBoard()
  } finally {
    saving.value = false
  }
}

async function submitStatus() {
  if (!currentId.value) return
  statusSaving.value = true
  try {
    await taskApi.changeStatus(currentId.value, targetStatus.value, targetProgress.value)
    ElMessage.success('状态已流转')
    logs.value = await taskApi.logs(currentId.value)
    await loadBoard()
  } finally {
    statusSaving.value = false
  }
}

async function addCheck() {
  if (!currentId.value || !newCheck.value.trim()) return
  checklist.value.push({ text: newCheck.value.trim(), done: false })
  const idx = checklist.value.length - 1
  newCheck.value = ''
  await taskApi.update(currentId.value, { checklist: checklist.value })
}

async function onToggleCheck(index: number, done: boolean) {
  if (!currentId.value) return
  checklist.value[index].done = done
  await taskApi.toggleChecklist(currentId.value, index, done)
}

async function doCancel() {
  if (!currentId.value) return
  await taskApi.cancel(currentId.value)
  ElMessage.success('任务已取消')
  drawerVisible.value = false
  await loadBoard()
}

onMounted(async () => {
  members.value = await taskApi.memberOptions().catch(() => [])
  await loadBoard()
  const focus = route.query.task ? Number(route.query.task) : null
  if (focus) {
    const task = board.value.flatMap((c) => c.tasks).find((t) => t.id === focus)
    if (task) await openDetail(task)
  }
})
</script>

<style scoped>
.board {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 12px;
}

.board-col {
  flex: 0 0 260px;
  background: #eef2f7;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 230px);
}

.col-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  font-weight: 600;
  font-size: 14px;
}

.col-title {
  display: flex;
  align-items: center;
  gap: 6px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.col-body {
  padding: 0 10px 10px;
  overflow-y: auto;
  min-height: 120px;
}

.task-card {
  background: #fff;
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 8px;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}

.task-card:hover {
  box-shadow: 0 3px 10px rgba(15, 23, 42, 0.14);
}

.task-card.is-overdue {
  border-left: 3px solid #f56c6c;
}

.task-card-title {
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 8px;
  line-height: 1.5;
}

.task-card-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #6b7280;
  flex-wrap: wrap;
}

.check-row {
  padding: 4px 0;
}

.line-through {
  text-decoration: line-through;
  color: #9ca3af;
}

.check-add {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
</style>
