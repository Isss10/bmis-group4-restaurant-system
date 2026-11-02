<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiError, roleNames, useAuth, type Role, type User, type UserPage } from './auth'

const auth = useAuth()
const mode = ref<'login' | 'register'>('login')
const busy = ref(false)
const loadingUsers = ref(false)
const errorMessage = ref('')
const form = reactive({ email: '', password: '', display_name: '' })
const staff = reactive({ email: '', password: '', display_name: '', role: 'waiter' as Role })
const creatingStaff = ref(false)
const users = ref<User[]>([])
const total = ref(0)
const page = ref(1)
const roleChoices: Role[] = ['customer', 'waiter', 'manager', 'admin']

function showError(error: unknown): void {
  if (error === 'cancel' || error === 'close') return
  errorMessage.value = error instanceof ApiError
    ? `${error.message}${error.requestId ? `（请求编号：${error.requestId}）` : ''}`
    : '无法连接服务，请确认网络和服务状态后重试。'
}

function checkPassword(password: string): boolean {
  if (Array.from(password).length < 12 || new TextEncoder().encode(password).length > 72) {
    errorMessage.value = '密码至少 12 个字符，UTF-8 编码不超过 72 字节。'
    return false
  }
  return true
}

async function submit(): Promise<void> {
  errorMessage.value = ''
  if (mode.value === 'register' && !checkPassword(form.password)) return
  busy.value = true
  try {
    if (mode.value === 'register') {
      await auth.register(form.email, form.password, form.display_name)
      mode.value = 'login'
      ElMessage.success('注册成功，请登录。')
    } else {
      await auth.login(form.email, form.password)
    }
  } catch (error) { showError(error) }
  finally { form.password = ''; busy.value = false }
}

async function logout(): Promise<void> {
  errorMessage.value = ''
  busy.value = true
  try { await auth.logout() }
  catch (error) { showError(error) }
  finally { users.value = []; busy.value = false }
}

async function loadUsers(): Promise<void> {
  if (auth.user?.role !== 'admin') return
  loadingUsers.value = true
  try {
    const data = await auth.request<UserPage>(`/users?page=${page.value}&page_size=20`)
    users.value = data.items
    total.value = data.total
  } catch (error) { showError(error) }
  finally { loadingUsers.value = false }
}

async function createStaff(): Promise<void> {
  errorMessage.value = ''
  if (!checkPassword(staff.password)) return
  busy.value = true
  try {
    await auth.request<User>('/users', { method: 'POST', body: JSON.stringify(staff) })
    creatingStaff.value = false
    Object.assign(staff, { email: '', password: '', display_name: '', role: 'waiter' })
    ElMessage.success('账号已创建。')
    await loadUsers()
  } catch (error) { showError(error) }
  finally { busy.value = false; staff.password = '' }
}

async function changeRole(target: User, role: Role): Promise<void> {
  if (target.role === role) return
  errorMessage.value = ''
  try {
    await ElMessageBox.confirm(
      `将「${target.display_name}」从${roleNames[target.role]}改为${roleNames[role]}？其已有登录会话将失效。`,
      '确认修改角色', { confirmButtonText: '确认修改', cancelButtonText: '取消', type: 'warning' },
    )
    await auth.request<User>(`/users/${target.id}/role`, {
      method: 'PATCH', body: JSON.stringify({ role, version: target.version }),
    })
    if (target.id === auth.user?.id) {
      await auth.logout()
      ElMessage.info('你的权限已改变，请重新登录。')
    } else { await loadUsers(); ElMessage.success('角色已更新。') }
  } catch (error) {
    showError(error)
    if (error instanceof ApiError && error.status === 409) await loadUsers()
  }
}

async function changeStatus(target: User): Promise<void> {
  errorMessage.value = ''
  try {
    await ElMessageBox.confirm(
      `${target.is_active ? '停用' : '启用'}「${target.display_name}」？${target.is_active ? '其已有登录会话将失效。' : ''}`,
      '确认修改账号状态', { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' },
    )
    await auth.request<User>(`/users/${target.id}/status`, {
      method: 'PATCH', body: JSON.stringify({ is_active: !target.is_active, version: target.version }),
    })
    if (target.id === auth.user?.id) { await auth.logout() }
    else { await loadUsers(); ElMessage.success('账号状态已更新。') }
  } catch (error) {
    showError(error)
    if (error instanceof ApiError && error.status === 409) await loadUsers()
  }
}

watch(() => auth.user?.id, () => { page.value = 1; void loadUsers() })
watch(page, () => { void loadUsers() })
watch(mode, () => { errorMessage.value = ''; form.password = '' })
onMounted(async () => {
  try { await auth.restore() }
  catch (error) { showError(error) }
})
</script>

<template>
  <div class="page-shell">
    <header class="site-header">
      <a class="brand" href="/" aria-label="会员中心首页"><span class="brand-mark">G4</span><span>GROUP 4 <small>RESTAURANT</small></span></a>
      <span class="header-label">会员中心</span>
    </header>

    <main>
      <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon class="page-error" @close="errorMessage = ''" />
      <div v-if="auth.restoring" class="restoring" role="status">正在恢复登录状态…</div>

      <section v-else-if="!auth.authenticated" class="welcome-grid">
        <div class="welcome-copy">
          <span class="eyebrow">YOUR TABLE, YOUR MOMENTS</span>
          <h1>美味相聚，<br />从这里开始。</h1>
          <p>登录你的餐厅账号，开启预约、点餐与会员服务。</p>
          <div class="welcome-note"><span>01</span><div><strong>一个账号，连接每次用餐</strong><p>顾客与员工使用各自的账号登录。</p></div></div>
        </div>
        <div class="auth-panel">
          <span class="eyebrow">WELCOME TO GROUP 4</span>
          <h2>{{ mode === 'login' ? '欢迎回来' : '创建顾客账号' }}</h2>
          <p class="panel-description">{{ mode === 'login' ? '使用邮箱和密码登录。' : '填写资料，开始你的会员体验。' }}</p>
          <el-form label-position="top" @submit.prevent="submit">
            <el-form-item v-if="mode === 'register'" label="称呼">
              <el-input v-model="form.display_name" maxlength="80" autocomplete="name" required placeholder="我们应该如何称呼你" />
            </el-form-item>
            <el-form-item label="邮箱">
              <el-input v-model="form.email" type="email" maxlength="254" autocomplete="username" required placeholder="name@example.com" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="form.password" type="password" show-password :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" required placeholder="输入密码" />
              <span v-if="mode === 'register'" class="field-hint">至少 12 个字符，UTF-8 编码不超过 72 字节。</span>
            </el-form-item>
            <el-button type="primary" native-type="submit" :loading="busy" class="full-width">{{ mode === 'login' ? '登录' : '注册顾客账号' }}</el-button>
          </el-form>
          <div class="switch-mode">
            {{ mode === 'login' ? '还没有账号？' : '已有账号？' }}
            <el-button link type="primary" :disabled="busy" @click="mode = mode === 'login' ? 'register' : 'login'">{{ mode === 'login' ? '立即注册' : '返回登录' }}</el-button>
          </div>
          <p class="auth-footnote">员工账号由管理员创建。</p>
        </div>
      </section>

      <section v-else-if="auth.user" class="dashboard">
        <div class="dashboard-heading">
          <div><span class="eyebrow">MY ACCOUNT</span><h1>你好，{{ auth.user.display_name }}</h1><p>欢迎来到你的餐厅账号中心。</p></div>
          <el-button :loading="busy" @click="logout">退出登录</el-button>
        </div>
        <div class="profile-grid">
          <article class="profile-card"><span class="card-label">账号资料</span><h2>{{ auth.user.display_name }}</h2><p>{{ auth.user.email }}</p><el-tag effect="plain">{{ roleNames[auth.user.role] }}</el-tag></article>
          <article class="loyalty-card"><span class="card-label">会员服务</span><h2>每次相聚，都值得记录。</h2><p>积分、会员等级与优惠券将在对应模块接入后展示。</p></article>
        </div>

        <section v-if="auth.user.role === 'admin'" class="admin-panel">
          <div class="section-heading"><div><span class="eyebrow">ADMINISTRATION</span><h2>账号管理</h2><p>管理账号角色和使用状态。</p></div><el-button type="primary" @click="creatingStaff = true">创建账号</el-button></div>
          <div class="table-scroll"><el-table v-loading="loadingUsers" :data="users" stripe empty-text="暂无账号">
            <el-table-column prop="display_name" label="称呼" min-width="140" />
            <el-table-column prop="email" label="邮箱" min-width="220" />
            <el-table-column label="角色" width="140"><template #default="scope"><el-select :model-value="scope.row.role" aria-label="修改账号角色" @change="(role: Role) => changeRole(scope.row, role)"><el-option v-for="role in roleChoices" :key="role" :label="roleNames[role]" :value="role" /></el-select></template></el-table-column>
            <el-table-column label="状态" width="100"><template #default="scope"><el-tag :type="scope.row.is_active ? 'success' : 'info'">{{ scope.row.is_active ? '正常' : '已停用' }}</el-tag></template></el-table-column>
            <el-table-column label="操作" width="110"><template #default="scope"><el-button link :type="scope.row.is_active ? 'danger' : 'primary'" @click="changeStatus(scope.row)">{{ scope.row.is_active ? '停用账号' : '启用账号' }}</el-button></template></el-table-column>
          </el-table></div>
          <el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" class="pagination" />
        </section>
      </section>
    </main>

    <footer>JC2001 · BMIS GROUP 4 <span>用心连接每一次相聚</span></footer>

    <el-dialog v-model="creatingStaff" title="创建账号" width="min(460px, 92vw)" :close-on-click-modal="false" @closed="staff.password = ''">
      <el-form label-position="top" @submit.prevent="createStaff">
        <el-form-item label="称呼"><el-input v-model="staff.display_name" maxlength="80" required autocomplete="off" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="staff.email" type="email" maxlength="254" required autocomplete="off" /></el-form-item>
        <el-form-item label="初始密码"><el-input v-model="staff.password" type="password" show-password required autocomplete="new-password" /><span class="field-hint">至少 12 个字符，UTF-8 编码不超过 72 字节。</span></el-form-item>
        <el-form-item label="角色"><el-select v-model="staff.role" class="full-width"><el-option v-for="role in roleChoices" :key="role" :label="roleNames[role]" :value="role" /></el-select></el-form-item>
        <el-button type="primary" native-type="submit" :loading="busy" class="full-width">创建账号</el-button>
      </el-form>
    </el-dialog>
  </div>
</template>
