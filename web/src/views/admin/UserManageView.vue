<template>
  <div class="page-container">
    <div class="page-card">
      <div class="flex-between">
        <span class="page-title" style="margin: 0">用户管理</span>
        <div>
          <el-input
            v-model="keyword"
            placeholder="登录名/姓名"
            clearable
            style="width: 200px; margin-right: 8px"
            @keyup.enter="loadUsers"
          />
          <el-button @click="loadUsers"><el-icon><Refresh /></el-icon></el-button>
          <el-button type="primary" @click="openCreate">新建用户</el-button>
        </div>
      </div>

      <el-table :data="users" border stripe size="small" style="margin-top: 14px" v-loading="loading">
        <el-table-column prop="username" label="登录名" width="140" />
        <el-table-column prop="full_name" label="姓名" width="120" />
        <el-table-column prop="email" label="邮箱" min-width="180" />
        <el-table-column label="所属部门" min-width="180">
          <template #default="{ row }">
            <el-tag
              v-for="name in row.department_names"
              :key="name"
              size="small"
              style="margin-right: 4px"
            >
              {{ name }}
            </el-tag>
            <span v-if="!row.department_names?.length" class="muted">未分配</span>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="180">
          <template #default="{ row }">
            <el-tag v-if="row.is_superuser" type="danger" size="small">管理员</el-tag>
            <el-tag v-else-if="row.leader_department_ids?.length" type="warning" size="small">
              组长
            </el-tag>
            <el-tag v-else size="small" type="info">成员</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="认证来源" width="150">
          <template #default="{ row }">
            <el-tag :type="row.is_sso ? 'warning' : 'info'" size="small">
              {{ row.auth_source_label || (row.is_sso ? '统一身份认证' : '本地口令') }}
            </el-tag>
            <div v-if="row.external_id" class="muted external-id">
              {{ row.external_id }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '在职' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button text :disabled="row.is_sso" @click="doReset(row)">重置密码</el-button>
            <el-button text type="warning" @click="openBind(row)">
              {{ row.is_sso ? '解绑' : '绑定认证' }}
            </el-button>
            <el-button text type="danger" @click="doRemove(row)">停用</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        style="margin-top: 12px; justify-content: flex-end"
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page="page"
        @current-change="onPage"
      />
    </div>

    <el-drawer v-model="drawerVisible" :title="editing ? '编辑用户' : '新建用户'" size="520px">
      <el-form label-width="96px">
        <el-form-item label="登录名" required v-if="!editing">
          <el-input v-model="form.username" placeholder="3-64 位字母/数字/下划线" />
        </el-form-item>
        <el-form-item label="姓名" required>
          <el-input v-model="form.full_name" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" />
        </el-form-item>
        <el-form-item label="所属部门">
          <el-select v-model="form.department_ids" multiple style="width: 100%">
            <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="担任组长">
          <el-select v-model="form.leader_department_ids" multiple style="width: 100%">
            <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="系统角色">
          <el-radio-group v-model="form.is_superuser">
            <el-radio :value="false">普通成员</el-radio>
            <el-radio :value="true">管理员</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="在职状态">
          <el-switch v-model="form.is_active" active-text="在职" inactive-text="停用" />
        </el-form-item>
        <el-form-item label="初始密码" v-if="!editing">
          <el-input v-model="form.password" type="password" show-password placeholder="留空则自动生成" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="drawerVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-drawer>

    <el-dialog v-model="bindVisible" :title="bindRow?.is_sso ? '解绑统一身份' : '绑定统一身份'" width="520px">
      <template v-if="bindRow?.is_sso">
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          title="解绑后该账号恢复本地口令登录"
          description="系统会生成一个随机初始口令并强制该成员首次登录时修改。请确认该成员仍能通过本地方式登录，避免被锁在系统外。"
        />
        <el-form label-width="110px" style="margin-top: 14px">
          <el-form-item label="当前绑定">
            <span>{{ bindRow.auth_source_label }} · {{ bindRow.external_id }}</span>
          </el-form-item>
        </el-form>
      </template>
      <template v-else>
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="绑定后该账号改为统一身份认证登录"
          description="本地口令会被清除。管理员账号请谨慎操作 —— 一旦绑定且 IdP 不可用，将失去本地应急登录通道。"
        />
        <el-form label-width="110px" style="margin-top: 14px">
          <el-form-item label="认证来源" required>
            <el-select v-model="bindForm.source" style="width: 100%">
              <el-option
                v-for="c in bindChoices"
                :key="c.id"
                :label="c.label"
                :value="c.source"
                :disabled="!c.supported"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="IdP 用户标识" required>
            <el-input
              v-model="bindForm.external_id"
              placeholder="CAS 用户名 / OIDC sub / LDAP DN"
            />
          </el-form-item>
        </el-form>
      </template>
      <template #footer>
        <el-button @click="bindVisible = false">取消</el-button>
        <el-button type="primary" :loading="binding" @click="submitBind">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="pwdVisible" title="临时密码（仅显示一次）" width="440px">
      <el-alert
        type="warning"
        :closable="false"
        title="请立即复制并安全转达给该成员。系统不保存明文密码，此窗口关闭后无法再次查看。"
      />
      <div class="temp-pwd">{{ tempPassword }}</div>
      <template #footer>
        <el-button type="primary" @click="pwdVisible = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { departmentApi, userApi } from '@/api/organization'
import { authApi } from '@/api/auth'
import type { DepartmentItem, UserItem } from '@/types'

const loading = ref(false)
const saving = ref(false)
const drawerVisible = ref(false)
const pwdVisible = ref(false)
const tempPassword = ref('')
const editing = ref<UserItem | null>(null)
const users = ref<UserItem[]>([])
const departments = ref<DepartmentItem[]>([])
const keyword = ref('')
const page = ref(1)
const pageSize = 20
const total = ref(0)

// ---- 统一身份绑定 ----
const bindVisible = ref(false)
const binding = ref(false)
const bindRow = ref<UserItem | null>(null)
const bindForm = ref({ source: 'cas', external_id: '' })
const ssoChoices = ref<{ id: string; label: string; source: string; supported: boolean }[]>([])
const bindChoices = computed(() => ssoChoices.value)

const form = ref({
  username: '',
  full_name: '',
  email: '',
  department_ids: [] as number[],
  leader_department_ids: [] as number[],
  is_superuser: false,
  is_active: true,
  password: '',
})

async function loadUsers() {
  loading.value = true
  try {
    const res = await userApi.list({
      page: page.value,
      page_size: pageSize,
      keyword: keyword.value || undefined,
    })
    users.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function onPage(p: number) {
  page.value = p
  loadUsers()
}

function openCreate() {
  editing.value = null
  form.value = {
    username: '',
    full_name: '',
    email: '',
    department_ids: [],
    leader_department_ids: [],
    is_superuser: false,
    is_active: true,
    password: '',
  }
  drawerVisible.value = true
}

function openEdit(row: UserItem) {
  editing.value = row
  form.value = {
    username: row.username,
    full_name: row.full_name,
    email: row.email ?? '',
    department_ids: [...row.department_ids],
    leader_department_ids: [...row.leader_department_ids],
    is_superuser: row.is_superuser,
    is_active: row.is_active,
    password: '',
  }
  drawerVisible.value = true
}

async function submit() {
  saving.value = true
  try {
    if (editing.value) {
      await userApi.update(editing.value.id, {
        full_name: form.value.full_name,
        email: form.value.email || null,
        department_ids: form.value.department_ids,
        leader_department_ids: form.value.leader_department_ids,
        is_superuser: form.value.is_superuser,
        is_active: form.value.is_active,
      })
      ElMessage.success('已保存')
      drawerVisible.value = false
    } else {
      const res = await userApi.create({
        username: form.value.username,
        full_name: form.value.full_name,
        email: form.value.email || null,
        department_ids: form.value.department_ids,
        leader_department_ids: form.value.leader_department_ids,
        is_superuser: form.value.is_superuser,
        is_active: form.value.is_active,
        password: form.value.password || null,
      })
      tempPassword.value = res.temp_password
      ElMessage.success('用户已创建')
      drawerVisible.value = false
      pwdVisible.value = true
    }
    await loadUsers()
  } finally {
    saving.value = false
  }
}

async function doReset(row: UserItem) {
  await ElMessageBox.confirm(`确认重置 ${row.full_name} 的登录密码？`, '提示', { type: 'warning' })
  const res = await userApi.resetPassword(row.id)
  tempPassword.value = res.temp_password
  pwdVisible.value = true
}

async function openBind(row: UserItem) {
  bindRow.value = row
  bindForm.value = { source: ssoChoices.value[0]?.source ?? 'cas', external_id: '' }
  bindVisible.value = true
}

async function submitBind() {
  const row = bindRow.value
  if (!row) return
  if (!row.is_sso && (!bindForm.value.source || !bindForm.value.external_id.trim())) {
    ElMessage.warning('请填写认证来源与 IdP 用户标识')
    return
  }
  binding.value = true
  try {
    if (row.is_sso) {
      await ElMessageBox.confirm(
        `确认解绑 ${row.full_name} 的统一身份？解绑后需使用本地口令登录。`,
        '提示',
        { type: 'warning' },
      )
      const res = await userApi.ssoUnbind(row.id)
      tempPassword.value = res.temp_password
      bindVisible.value = false
      pwdVisible.value = true
      ElMessage.success('已解绑，请转告该成员使用新口令登录')
    } else {
      await userApi.ssoBind(row.id, {
        source: bindForm.value.source,
        external_id: bindForm.value.external_id.trim(),
      })
      ElMessage.success('已绑定统一身份')
      bindVisible.value = false
    }
    await loadUsers()
  } finally {
    binding.value = false
  }
}

async function doRemove(row: UserItem) {
  await ElMessageBox.confirm(
    `确认停用 ${row.full_name}？停用后不再计入周报应提交名单。`,
    '提示',
    { type: 'warning' },
  )
  await userApi.update(row.id, { is_active: false })
  ElMessage.success('已停用')
  await loadUsers()
}

onMounted(async () => {
  departments.value = await departmentApi.list().catch(() => [])
  const cfg = await authApi.ssoConfig().catch(() => null)
  ssoChoices.value = cfg?.choices ?? []
  await loadUsers()
})
</script>

<style scoped>
.temp-pwd {
  margin-top: 14px;
  padding: 14px;
  background: #f1f5f9;
  border-radius: 6px;
  font-family: Consolas, monospace;
  font-size: 18px;
  text-align: center;
  letter-spacing: 1px;
  user-select: all;
}

.external-id {
  margin-top: 2px;
  font-size: 12px;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
