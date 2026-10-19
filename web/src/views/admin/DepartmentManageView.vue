<template>
  <div class="page-container">
    <div class="page-card">
      <div class="flex-between">
        <span class="page-title" style="margin: 0">部门管理</span>
        <div>
          <el-button @click="loadList"><el-icon><Refresh /></el-icon></el-button>
          <el-button type="primary" @click="openCreate">新建部门</el-button>
        </div>
      </div>

      <el-row :gutter="14" style="margin-top: 14px" v-loading="loading">
        <el-col
          v-for="d in departments"
          :key="d.id"
          :xs="24"
          :md="12"
          :lg="8"
          style="margin-bottom: 14px"
        >
          <el-card shadow="never">
            <template #header>
              <div class="flex-between">
                <span class="dept-name">{{ d.name }}</span>
                <el-tag :type="d.is_active ? 'success' : 'info'" size="small">
                  {{ d.is_active ? '启用' : '停用' }} · {{ d.member_count }} 人
                </el-tag>
              </div>
            </template>
            <div class="member-list">
              <div v-for="m in d.members" :key="m.user_id" class="member-row">
                <span>
                  {{ m.full_name }}
                  <el-tag v-if="m.is_leader" size="small" type="warning">组长</el-tag>
                </span>
                <el-button text type="danger" @click="removeMember(d, m.user_id)">移除</el-button>
              </div>
              <el-empty v-if="!d.members.length" description="暂无成员" :image-size="50" />
            </div>
            <div class="dept-actions">
              <el-select
                v-model="picked[d.id]"
                filterable
                placeholder="添加成员"
                style="flex: 1"
              >
                <el-option
                  v-for="u in users"
                  :key="u.id"
                  :label="`${u.full_name}（${u.username}）`"
                  :value="u.id"
                />
              </el-select>
              <el-button type="primary" @click="addMember(d)">添加</el-button>
              <el-button @click="openEdit(d)">编辑</el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>
      <el-empty v-if="!loading && !departments.length" description="暂无部门" />
    </div>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑部门' : '新建部门'" width="480px">
      <el-form label-width="90px">
        <el-form-item label="部门名称" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="上级部门">
          <el-select v-model="form.parent_id" clearable style="width: 100%">
            <el-option
              v-for="d in departments"
              :key="d.id"
              :label="d.name"
              :value="d.id"
              :disabled="d.id === editing?.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="部门负责人">
          <el-select v-model="form.leader_id" filterable clearable style="width: 100%">
            <el-option v-for="u in users" :key="u.id" :label="u.full_name" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="显示排序">
          <el-input-number v-model="form.sort_order" :min="0" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { departmentApi, userApi } from '@/api/organization'
import type { DepartmentItem, UserItem } from '@/types'

const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const departments = ref<DepartmentItem[]>([])
const users = ref<UserItem[]>([])
const editing = ref<DepartmentItem | null>(null)
const picked = reactive<Record<number, number | undefined>>({})

const form = ref({
  name: '',
  parent_id: undefined as number | undefined,
  leader_id: undefined as number | undefined,
  sort_order: 0,
  is_active: true,
})

async function loadList() {
  loading.value = true
  try {
    departments.value = await departmentApi.list()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.value = {
    name: '',
    parent_id: undefined,
    leader_id: undefined,
    sort_order: 0,
    is_active: true,
  }
  dialogVisible.value = true
}

function openEdit(d: DepartmentItem) {
  editing.value = d
  form.value = {
    name: d.name,
    parent_id: d.parent_id ?? undefined,
    leader_id: d.leader_id ?? undefined,
    sort_order: d.sort_order,
    is_active: d.is_active,
  }
  dialogVisible.value = true
}

async function submit() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写部门名称')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await departmentApi.update(editing.value.id, {
        name: form.value.name,
        parent_id: form.value.parent_id ?? null,
        leader_id: form.value.leader_id ?? null,
        sort_order: form.value.sort_order,
        is_active: form.value.is_active,
      })
      ElMessage.success('已保存')
    } else {
      await departmentApi.create({
        name: form.value.name,
        parent_id: form.value.parent_id ?? null,
        leader_id: form.value.leader_id ?? null,
        sort_order: form.value.sort_order,
      })
      ElMessage.success('部门已创建')
    }
    dialogVisible.value = false
    await loadList()
  } finally {
    saving.value = false
  }
}

async function addMember(d: DepartmentItem) {
  const uid = picked[d.id]
  if (!uid) {
    ElMessage.warning('请先选择成员')
    return
  }
  await departmentApi.assignMember(d.id, uid)
  picked[d.id] = undefined
  ElMessage.success('成员已添加')
  await loadList()
}

async function removeMember(d: DepartmentItem, userId: number) {
  await departmentApi.removeMember(d.id, userId)
  ElMessage.success('已移除')
  await loadList()
}

onMounted(async () => {
  const res = await userApi.list({ page_size: 200 }).catch(() => null)
  users.value = res?.items ?? []
  await loadList()
})
</script>

<style scoped>
.dept-name {
  font-size: 15px;
  font-weight: 600;
}

.member-list {
  max-height: 220px;
  overflow-y: auto;
}

.member-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 0;
  border-bottom: 1px dashed #eef2f7;
  font-size: 13px;
}

.dept-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
</style>
