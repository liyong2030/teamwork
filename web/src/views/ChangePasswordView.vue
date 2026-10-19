<template>
  <div class="login-page">
    <div class="pwd-box">
      <h2>{{ mustChange ? '首次登录，请修改密码' : '修改密码' }}</h2>
      <p class="muted" v-if="mustChange">
        出于安全要求，必须更换初始密码后才能继续使用系统。请先输入管理员下发的初始密码。
      </p>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px" class="pwd-form">
        <el-form-item label="原密码" prop="oldPassword">
          <el-input v-model="form.oldPassword" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码" prop="newPassword">
          <el-input v-model="form.newPassword" type="password" show-password />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirm">
          <el-input v-model="form.confirm" type="password" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="onSubmit">确认修改</el-button>
          <el-button v-if="!mustChange" @click="router.push({ name: 'dashboard' })">返回</el-button>
        </el-form-item>
      </el-form>
      <div class="policy">
        <div>密码策略：</div>
        <ul>
          <li>长度不少于 {{ policy.min_length }} 位</li>
          <li>需包含大写字母、小写字母、数字、符号中的至少 {{ policy.require_classes }} 类</li>
          <li>不能包含空格</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { authApi } from '@/api/auth'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const store = useUserStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const policy = ref({ min_length: 10, require_classes: 3 })

const form = ref({ oldPassword: '', newPassword: '', confirm: '' })

const mustChange = computed(() => !!store.profile?.must_change_password)

const rules: FormRules = {
  oldPassword: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { validator: validateStrength, trigger: 'blur' },
  ],
  confirm: [{ validator: validateConfirm, trigger: 'blur' }],
}

function validateStrength(_rule: unknown, value: string, callback: (e?: Error) => void) {
  if (!value) return callback()
  if (value.includes(' ')) return callback(new Error('密码不能包含空格'))
  if (value.length < policy.value.min_length) {
    return callback(new Error(`密码长度不少于 ${policy.value.min_length} 位`))
  }
  const groups = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(value)).length
  if (groups < policy.value.require_classes) {
    return callback(new Error(`需包含大小写字母、数字、符号中的至少 ${policy.value.require_classes} 类`))
  }
  callback()
}

function validateConfirm(_rule: unknown, value: string, callback: (e?: Error) => void) {
  if (value !== form.value.newPassword) return callback(new Error('两次输入的密码不一致'))
  callback()
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await authApi.changePassword(form.value.oldPassword, form.value.newPassword)
    ElMessage.success('密码已更新，请使用新密码重新登录')
    store.logout()
    router.push({ name: 'login' })
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    policy.value = await authApi.passwordPolicy()
  } catch {
    /* 使用默认策略 */
  }
})
</script>

<style scoped>
.login-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f3b6f 0%, #2f5597 60%, #4a7cc7 100%);
}

.pwd-box {
  width: 460px;
  padding: 32px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(15, 23, 42, 0.22);
}

.pwd-box h2 {
  margin: 0 0 6px;
  font-size: 19px;
  color: #16222f;
}

.pwd-form {
  margin-top: 18px;
}

.policy {
  margin-top: 12px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 6px;
  font-size: 12px;
  color: #4b5563;
  line-height: 1.8;
}

.policy ul {
  margin: 4px 0 0;
  padding-left: 18px;
}
</style>
