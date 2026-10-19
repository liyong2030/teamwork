import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { CurrentUser } from '@/types'
import { tokenStore } from '@/api/http'

export const useUserStore = defineStore('user', () => {
  const profile = ref<CurrentUser | null>(null)
  const accessToken = ref<string>(tokenStore.access)

  function setProfile(data: CurrentUser) {
    profile.value = data
  }

  function setTokens(access: string, refresh: string) {
    tokenStore.access = access
    tokenStore.refresh = refresh
    accessToken.value = access
  }

  function clearPasswordFlag() {
    if (profile.value) {
      profile.value = { ...profile.value, must_change_password: false }
    }
  }

  function logout() {
    profile.value = null
    accessToken.value = ''
    tokenStore.clear()
  }

  const displayName = computed(() => profile.value?.full_name || profile.value?.username || '')
  const isAdmin = computed(() => !!profile.value?.is_superuser)
  const isLeader = computed(() => !!profile.value?.is_superuser || !!profile.value?.is_department_leader)
  const isMemberOnly = computed(() => !isLeader.value)

  return {
    profile,
    accessToken,
    setProfile,
    setTokens,
    clearPasswordFlag,
    logout,
    displayName,
    isAdmin,
    isLeader,
    isMemberOnly,
  }
})
