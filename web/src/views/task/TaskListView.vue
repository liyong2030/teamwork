<template>
  <div class="page-container">
    <div class="page-card">
      <div class="flex-between">
        <span class="page-title" style="margin: 0">任务列表</span>
        <div>
          <el-select
            v-model="filters.status"
            placeholder="全部状态"
            clearable
            style="width: 130px"
            @change="loadTasks"
          >
            <el-option
              v-for="(v, k) in TASK_STATUS_MAP"
              :key="k"
              :label="v.label"
              :value="k"
            />
          </el-select>
          <el-input
            v-model="filters.keyword"
            placeholder="搜索标题"
            clearable
            style="width: 180px; margin: 0 8px"
            @keyup.enter="loadTasks"
          />
          <el-button type="primary" @click="openCreate">
            <el-icon><Plus /></el-icon>
            新建任务
          </el-button>
        </div>
      </div>

      <el-alert
        type="info"
        :closable="false"
        show-icon
        style="margin-top: 12px"
        title="按可见范围展示：普通成员仅能看到负责人为自己、或协作人包含自己的任务；组长与管理员可见本部门范围内的任务。"
      />

      <el-table :data="tasks" border stripe size="small" style="margin-top: 14px" v-loading="loading">
        <el-table-column prop="title" label="任务标题" min-width="220" show-overflow-tooltip />
        <el-table-column prop="project_name" label="所属项目" width="150" />
        <el-table-column label="负责人" width="110">
          <template #default="{ row }">{{ row.owner_name || '未指派' }}</template>
        </el-table-column>
        <el-table-column label="优先级" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="TASK_PRIORITY_MAP[row.priority]?.type">
              {{ row.priority }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="TASK_STATUS_MAP[row.status]?.type">
              {{ TASK_STATUS_MAP[row.status]?.label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="130">
          <template #default="{ row }">
            <el-progress :percentage="row.progress" :stroke-width="8" />
          </template>
        </el-table-column>
        <el-table-column label="截止日" width="120">
          <template #default="{ row }">
            <span :class="{ 'text-danger': row.is_overdue }">
              {{ row.due_date || '-' }}
              <el-tag v-if="row.is_overdue" size="small" type="danger">逾期</el-tag>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" @click="openDetail(row)">详情</el-button>
            <el-button text @click="changeStatus(row)">流转</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="drawerVisible" :title="isCreate ? '新建任务' : '任务详情'" size="620px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" placeholder="任务标题" />
        </el-form-item>
        <el-form-item label="所属项目" required>
          <el-select v-model="form.project_id" filterable style="width: 100%">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人">
          <el-select v-model="form.owner_id" filterable clearable style="width: 100%">
            <el-option
              v-for="m in members"
              :key="m.id"
              :label="`${m.full_name}（${m.username}）`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="协作人">
          <el-select v-model="form.collaborator_ids" multiple filterable style="width: 100%">
            <el-option
              v-for="m in members"
              :key="m.id"
              :label="m.full_name"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级">
          <el-select v-model="form.priority" style="width: 160px">
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
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日"
            end-placeholder="截止日"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="预估工时">
          <el-input-number v-model="form.estimated_hours" :min="0" :step="1" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>

      <el-divider content-position="left" v-if="!isCreate">状态流转</el-divider>
      <el-form v-if="!isCreate" :inline="true">
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
          <el-button type="primary" :loading="savingStatus" @click="submitStatusChange">
            保存流转
          </el-button>
        </el-form-item>
      </el-form>

      <el-divider content-position="left" v-if="!isCreate">状态流水</el-divider>
      <el-timeline v-if="!isCreate">
        <el-timeline-item
          v-for="log in logs"
          :key="log.id"
          :timestamp="formatDateTime(log.created_at)"
        >
          {{ TASK_STATUS_MAP[log.from_status ?? '']?.label || '新建' }} →
          {{ TASK_STATUS_MAP[log.to_status]?.label }}
          · {{ log.operator_name }}
          <span v-if="log.remark" class="muted">（{{ log.remark }}）</span>
        </el-timeline-item>
      </el-timeline>

      <template #footer>
        <el-button @click="drawerVisible = false">关闭</el-button>
        <el-button v-if="isCreate" type="primary" :loading="saving" @click="submitCreate">
          创建
        </el-button>
        <el-button v-else type="primary" :loading="saving" @click="submitUpdate">保存</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { projectApi } from '@/api/projects'
import { taskApi } from '@/api/tasks'
import { TASK_PRIORITY_MAP, TASK_STATUS_MAP, formatDateTime } from '@/utils/dict'
import type { MemberOption, ProjectItem, TaskItem, TaskLogItem } from '@/types'

const loading = ref(false)
const saving = ref(false)
const savingStatus = ref(false)
const drawerVisible = ref(false)
const isCreate = ref(false)
const tasks = ref<TaskItem[]>([])
const projects = ref<ProjectItem[]>([])
const members = ref<MemberOption[]>([])
const logs = ref<TaskLogItem[]>([])

const filters = ref({ status: '', keyword: '' })
const dateRange = ref<[string, string] | null>(null)
const currentId = ref<number | null>(null)
const targetStatus = ref('in_progress')
const targetProgress = ref(0)

const form = ref({
  title: '',
  project_id: undefined as number | undefined,
  owner_id: undefined as number | undefined,
  collaborator_ids: [] as number[],
  priority: 'p2',
  description: '',
  estimated_hours: undefined as number | undefined,
})

const formPayload = computed(() => ({
  title: form.value.title,
  project_id: form.value.project_id,
  owner_id: form.value.owner_id ?? null,
  collaborator_ids: form.value.collaborator_ids,
  priority: form.value.priority,
  description: form.value.description || null,
  estimated_hours: form.value.estimated_hours ?? null,
  start_date: dateRange.value?.[0] ?? null,
  due_date: dateRange.value?.[1] ?? null,
}))

async function loadTasks() {
  loading.value = true
  try {
    tasks.value = await taskApi.list({
      status: filters.value.status || undefined,
      keyword: filters.value.keyword || undefined,
      limit: 200,
    })
  } finally {
    loading.value = false
  }
}

function openCreate() {
  isCreate.value = true
  currentId.value = null
  form.value = {
    title: '',
    project_id: projects.value[0]?.id,
    owner_id: undefined,
    collaborator_ids: [],
    priority: 'p2',
    description: '',
    estimated_hours: undefined,
  }
  dateRange.value = null
  logs.value = []
  drawerVisible.value = true
}

async function openDetail(task: TaskItem) {
  isCreate.value = false
  currentId.value = task.id
  const full = await taskApi.detail(task.id)
  form.value = {
    title: full.title,
    project_id: full.project_id,
    owner_id: full.owner_id ?? undefined,
    collaborator_ids: full.collaborator_ids,
    priority: full.priority,
    description: full.description ?? '',
    estimated_hours: full.estimated_hours ?? undefined,
  }
  dateRange.value = full.start_date && full.due_date ? [full.start_date, full.due_date] : null
  targetStatus.value = full.status
  targetProgress.value = full.progress
  logs.value = await taskApi.logs(task.id)
  drawerVisible.value = true
}

function changeStatus(task: TaskItem) {
  openDetail(task)
}

async function submitCreate() {
  if (!form.value.title.trim()) {
    ElMessage.warning('请填写任务标题')
    return
  }
  if (!form.value.project_id) {
    ElMessage.warning('请选择所属项目')
    return
  }
  saving.value = true
  try {
    await taskApi.create(formPayload.value as never)
    ElMessage.success('任务已创建')
    drawerVisible.value = false
    await loadTasks()
  } finally {
    saving.value = false
  }
}

async function submitUpdate() {
  if (!currentId.value) return
  saving.value = true
  try {
    await taskApi.update(currentId.value, formPayload.value)
    ElMessage.success('任务已更新')
    drawerVisible.value = false
    await loadTasks()
  } finally {
    saving.value = false
  }
}

async function submitStatusChange() {
  if (!currentId.value) return
  savingStatus.value = true
  try {
    await taskApi.changeStatus(currentId.value, targetStatus.value, targetProgress.value)
    ElMessage.success('状态已更新')
    const full = await taskApi.detail(currentId.value)
    logs.value = await taskApi.logs(currentId.value)
    targetStatus.value = full.status
    await loadTasks()
  } finally {
    savingStatus.value = false
  }
}

onMounted(async () => {
  projects.value = await projectApi.list().catch(() => [])
  members.value = await taskApi.memberOptions().catch(() => [])
  await loadTasks()
})
</script>
