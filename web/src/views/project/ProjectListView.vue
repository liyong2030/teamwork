<template>
  <div class="page-container">
    <div class="page-card">
      <div class="flex-between">
        <span class="page-title" style="margin: 0">项目列表</span>
        <div>
          <el-input
            v-model="keyword"
            placeholder="搜索项目名/编号"
            clearable
            style="width: 220px; margin-right: 8px"
            @keyup.enter="loadProjects"
          />
          <el-button type="primary" @click="openCreateDialog">
            <el-icon><Plus /></el-icon>
            新建项目
          </el-button>
        </div>
      </div>

      <el-row :gutter="14" style="margin-top: 14px" v-loading="loading">
        <el-col
          v-for="p in projects"
          :key="p.id"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
          style="margin-bottom: 14px"
        >
          <el-card shadow="hover" class="project-card" @click="openBoard(p)">
            <template #header>
              <div class="flex-between">
                <span class="project-name" :title="p.name">{{ p.name }}</span>
                <el-tag size="small" :type="PROJECT_STATUS_MAP[p.status]?.type">
                  {{ PROJECT_STATUS_MAP[p.status]?.label || p.status }}
                </el-tag>
              </div>
            </template>
            <div class="project-code muted">{{ p.code }}</div>
            <div class="project-progress">
              <span class="muted">任务完成 {{ p.task_done }}/{{ p.task_total }}</span>
              <el-progress
                :percentage="percentOf(p)"
                :stroke-width="8"
                :status="percentOf(p) === 100 ? 'success' : undefined"
              />
            </div>
            <div class="project-foot">
              <span class="muted">负责人：{{ p.owner_name || '未指派' }}</span>
              <el-tag v-if="p.overdue_count" size="small" type="danger">
                逾期 {{ p.overdue_count }}
              </el-tag>
            </div>
          </el-card>
        </el-col>
      </el-row>
      <el-empty v-if="!loading && !projects.length" description="暂无可见项目" />
    </div>

    <el-dialog v-model="dialogVisible" title="新建项目" width="560px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="项目名称" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="项目编号">
          <el-input v-model="form.code" :placeholder="`留空自动生成（如 ${nextCode}）`" clearable />
        </el-form-item>
        <el-form-item label="归属部门">
          <el-select v-model="form.department_id" clearable style="width: 100%">
            <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人">
          <el-select v-model="form.owner_id" filterable clearable style="width: 100%">
            <el-option v-for="m in members" :key="m.id" :label="m.full_name" :value="m.id" />
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
        <el-form-item label="项目描述">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { departmentApi, userApi } from '@/api/organization'
import { projectApi } from '@/api/projects'
import { taskApi } from '@/api/tasks'
import { PROJECT_STATUS_MAP } from '@/utils/dict'
import type { DepartmentItem, MemberOption, ProjectItem, UserItem } from '@/types'

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const keyword = ref('')
const projects = ref<ProjectItem[]>([])
const departments = ref<DepartmentItem[]>([])
const members = ref<MemberOption[]>([])
const range = ref<[string, string] | null>(null)
const nextCode = ref('PRJ-0000-001')

const form = ref({
  name: '',
  code: '',
  department_id: undefined as number | undefined,
  owner_id: undefined as number | undefined,
  description: '',
})

function percentOf(p: ProjectItem) {
  if (!p.task_total) return 0
  return Math.round((p.task_done / p.task_total) * 100)
}

async function loadProjects() {
  loading.value = true
  try {
    projects.value = await projectApi.list({ keyword: keyword.value || undefined })
  } finally {
    loading.value = false
  }
}

function openBoard(p: ProjectItem) {
  router.push({ name: 'project-detail', params: { id: p.id } })
}

async function openCreateDialog() {
  dialogVisible.value = true
  // 编号改为后端自动生成，这里只取一个预览值做占位提示
  const res = await projectApi.nextCode().catch(() => null)
  if (res?.code) nextCode.value = res.code
}

async function submitCreate() {
  if (!form.value.name.trim()) {
    ElMessage.warning('项目名称必填')
    return
  }
  saving.value = true
  try {
    await projectApi.create({
      name: form.value.name,
      code: form.value.code?.trim() || null,
      department_id: form.value.department_id ?? null,
      owner_id: form.value.owner_id ?? null,
      description: form.value.description || null,
      start_date: range.value?.[0] ?? null,
      end_date: range.value?.[1] ?? null,
    })
    ElMessage.success('项目已创建')
    dialogVisible.value = false
    await loadProjects()
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  departments.value = await departmentApi.list().catch(() => [])
  members.value = await taskApi.memberOptions().catch(() => [])
  if (!members.value.length) {
    const res = await userApi.list({ page_size: 200 }).catch(() => null)
    members.value = (res?.items ?? []).map((u: UserItem) => ({
      id: u.id,
      username: u.username,
      full_name: u.full_name,
      email: u.email,
    }))
  }
  await loadProjects()
})
</script>

<style scoped>
.project-card {
  cursor: pointer;
}

.project-card:hover {
  border-color: var(--ctms-primary);
}

.project-name {
  font-size: 15px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-code {
  margin-bottom: 10px;
}

.project-progress {
  margin-bottom: 10px;
}

.project-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
