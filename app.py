import streamlit as st
import datetime
import uuid
import gspread
import json
from google.oauth2.service_account import Credentials

# --- 1. 구글 시트 연동 설정 ---
@st.cache_resource
def init_gsheets():
    skey = json.loads(st.secrets["gcp_json"])
    sheet_url = st.secrets["sheet_url"]
    
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    credentials = Credentials.from_service_account_info(skey, scopes=scopes)
    client = gspread.authorize(credentials)
    return client.open_by_url(sheet_url)

doc = init_gsheets()
ws_users = doc.worksheet("users")
ws_res = doc.worksheet("reservations")

# --- 초기 세션 설정 ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "is_admin" not in st.session_state:
    st.session_state["is_admin"] = False
if "current_user" not in st.session_state:
    st.session_state["current_user"] = ""
if "lesson_dates" not in st.session_state:
    st.session_state["lesson_dates"] = []
# 구글 시트 API 초과 방지를 위한 플래그 추가
if "data_loaded" not in st.session_state:
    st.session_state["data_loaded"] = False 
# 표가 접혀있는 상태를 기본값
if "table_expanded" not in st.session_state:
    st.session_state["table_expanded"] = False

# 데이터 불러오기 (최초 1회 또는 예약 변경 시에만 작동)
def load_data_from_db():
    if not st.session_state["data_loaded"]:
        users_records = ws_users.get_all_records()
        st.session_state["users"] = {str(r["name"]): str(r["password"]) for r in users_records}
        
        res_records = ws_res.get_all_records()
        st.session_state["reservations"] = [
            {
                "id": str(r["id"]),
                "date": str(r["date"]),
                "start_time": str(r["start_time"]),
                "end_time": str(r["end_time"]),
                "user_id": str(r["user_id"])
            } for r in res_records
        ]
        st.session_state["data_loaded"] = True

def rewrite_res_sheet():
    ws_res.clear()
    headers = ["id", "date", "start_time", "end_time", "user_id"]
    data = [headers]
    for r in st.session_state["reservations"]:
        data.append([r["id"], r["date"], r["start_time"], r["end_time"], r["user_id"]])
    ws_res.update(values=data, range_name="A1")

# --- 공통 시간 데이터 및 계산 ---
def get_all_time_slots():
    return [f"{h:02d}:{m:02d}" for h in range(6, 24) for m in (0, 30)]

all_time_slots = get_all_time_slots()
all_time_slots_with_24 = all_time_slots + ["24:00"]

def get_next_slot(t):
    if t == "23:30": return "24:00"
    h, m = map(int, t.split(":"))
    m += 30
    if m == 60:
        h += 1
        m = 0
    return f"{h:02d}:{m:02d}"

def get_duration_minutes(start_t, end_t):
    h1, m1 = map(int, start_t.split(":"))
    if end_t == "24:00":
        h2, m2 = 24, 0
    else:
        h2, m2 = map(int, end_t.split(":"))
    return (h2 * 60 + m2) - (h1 * 60 + m1)

# 앱이 실행될 때 데이터 동기화 시도 (조건부)
load_data_from_db()

# --- 화면 로직 ---
def login_screen():
    st.title("🥁프리모 드럼연습실 예약시스템")
    tab1, tab2 = st.tabs(["👨‍🎓 수강생 로그인", "👑 관리자 로그인"])
    with tab1:
        st.subheader("수강생 로그인")
        st.write("원장님께 부여받은 연습실 비밀번호를 입력해 주세요.")
        user_pwd = st.text_input("비밀번호", type="password", key="user_pwd_input")
        if st.button("수강생 입장하기"):
            matched_name = None
            for name, pwd in st.session_state["users"].items():
                if pwd == user_pwd:
                    matched_name = name
                    break
            if matched_name:
                st.session_state["logged_in"] = True
                st.session_state["is_admin"] = False
                st.session_state["current_user"] = matched_name
                st.rerun()
            else:
                st.error("일치하는 비밀번호가 없습니다. 다시 확인해 주세요.")

    with tab2:
        st.subheader("관리자 로그인")
        admin_pwd = st.text_input("관리자 비밀번호", type="password", key="admin_pwd_input")
        if st.button("관리자 입장하기"):
            if admin_pwd == "5843":
                st.session_state["logged_in"] = True
                st.session_state["is_admin"] = True
                st.session_state["current_user"] = "관리자"
                st.rerun()
            else:
                st.error("관리자 비밀번호가 틀렸습니다.")

def logout_button():
    if st.button("로그아웃", key="logout_btn"):
        st.session_state["logged_in"] = False
        st.session_state["is_admin"] = False
        st.session_state["current_user"] = ""
        st.rerun()

def user_page():
    st.info("📢 **안내:** 매월 고정 연습실 사용 예약은 010-2989-0601로 문의 바랍니다.")
    st.warning("⚠️ **개인 당 1일 최대 연습실 예약 가능 시간은 2시간으로 한정됩니다.**")
    st.write(f"환영합니다, **{st.session_state['current_user']}**님!")
    
    selected_date = st.date_input("예약하실 날짜를 선택하세요", datetime.date.today())
    
    st.markdown("---")
    col1, col2 = st.columns([1.2, 1])
    
    schedule_data = []
    for t in all_time_slots:
        end_t = get_next_slot(t)
        overlap = [r for r in st.session_state["reservations"] if r["date"] == str(selected_date) and r["start_time"] < end_t and r["end_time"] > t]
        display_time = f"{t} ~ {end_t}"
        if overlap:
            if overlap[0]["user_id"] == "관리자 고정일정":
                schedule_data.append({"시간": display_time, "상태": "🔒 고정일정"})
            elif overlap[0]["user_id"] == "레슨 일정":
                schedule_data.append({"시간": display_time, "상태": "🎸 레슨일정"})
            else:
                schedule_data.append({"시간": display_time, "상태": "🔴 예약마감"})
        else:
            schedule_data.append({"시간": display_time, "상태": "🟢 예약가능"})

    with col1:
        st.subheader(f"📅 {selected_date} 현황표")
        
        # 버튼 상태에 따라 표의 높이를 다르게 보여줍니다.
        if st.session_state["table_expanded"]:
            # 가로 길이를 320으로 고정하여 우측 여백 확보
            st.dataframe(schedule_data, use_container_width=False, width=320, hide_index=True, height=1300)
            if st.button("🔼 현황표 접기", use_container_width=True):
                st.session_state["table_expanded"] = False
                st.rerun()
        else:
            # 가로 길이를 320으로 고정하여 우측 여백 확보
            st.dataframe(schedule_data, use_container_width=False, width=320, hide_index=True, height=450)
            if st.button("🔽 전체 현황표 펼치기", use_container_width=True):
                st.session_state["table_expanded"] = True
                st.rerun()
        
    with col2:
        st.subheader("🕒 예약하기")
        start_time = st.selectbox("예약 시작 시간", all_time_slots)
        valid_end_times = [t for t in all_time_slots_with_24 if t > start_time]
        end_time = st.selectbox("예약 종료 시간", valid_end_times)
        requested_minutes = get_duration_minutes(start_time, end_time)
        st.caption(f"💡 선택하신 예약: **{start_time} 부터 {end_time} 까지 (총 {requested_minutes}분)**")
        
        if st.button("예약 확정"):
            is_overlap = any(r["date"] == str(selected_date) and r["start_time"] < end_time and r["end_time"] > start_time for r in st.session_state["reservations"])
            user_today_res = [r for r in st.session_state["reservations"] if r["date"] == str(selected_date) and r["user_id"] == st.session_state["current_user"]]
            existing_minutes = sum(get_duration_minutes(r["start_time"], r["end_time"]) for r in user_today_res)
            
            if existing_minutes + requested_minutes > 120:
                st.error(f"하루 최대 예약 가능 시간은 2시간(120분)입니다.\n\n현재 예약된 시간: {existing_minutes}분 / 추가하려는 시간: {requested_minutes}분")
            elif is_overlap:
                st.error("선택하신 시간대에 이미 다른 예약(또는 고정/레슨일정)이 포함되어 있습니다.")
            else:
                res_id = str(uuid.uuid4())
                ws_res.append_row([res_id, str(selected_date), start_time, end_time, st.session_state["current_user"]])
                st.session_state["data_loaded"] = False
                st.success("예약이 성공적으로 완료되었습니다!")
                st.rerun()

    st.markdown("---")
    st.subheader("나의 예약 내역")
    my_res = [r for r in st.session_state["reservations"] if r["user_id"] == st.session_state["current_user"]]
    if not my_res:
        st.write("예약된 내역이 없습니다.")
    else:
        my_res = sorted(my_res, key=lambda x: (x["date"], x["start_time"]))
        for r in my_res:
            cols = st.columns([3, 1])
            cols[0].write(f"✅ **{r['date']}** | {r['start_time']} ~ {r['end_time']}")
            if cols[1].button("예약 취소", key=f"cancel_{r['id']}"):
                try:
                    cell = ws_res.find(r["id"], in_column=1)
                    if cell: ws_res.delete_rows(cell.row)
                except: pass
                st.session_state["data_loaded"] = False
                st.rerun()

def admin_page():
    st.subheader("👑 관리자 대시보드")
    with st.expander("👥 수강생 계정 관리", expanded=False):
        st.write("**새로운 수강생 등록**")
        col1, col2 = st.columns(2)
        with col1:
            new_user_name = st.text_input("수강생 이름")
        with col2:
            new_user_pwd = st.text_input("부여할 비밀번호")
            
        if st.button("계정 등록"):
            if new_user_name and new_user_pwd:
                if new_user_pwd in st.session_state["users"].values():
                    st.error("이미 다른 수강생이 사용 중인 비밀번호입니다.")
                elif new_user_name in st.session_state["users"]:
                    st.error("이미 존재하는 이름입니다. 다른 이름(예: 홍길동A)으로 등록해 주세요.")
                else:
                    ws_users.append_row([new_user_name, new_user_pwd])
                    st.session_state["data_loaded"] = False
                    st.success(f"'{new_user_name}' 수강생이 등록되었습니다.")
                    st.rerun()
            else:
                st.warning("이름과 비밀번호를 모두 입력해 주세요.")
                
        st.markdown("---")
        st.write("**현재 등록된 수강생 목록 (수정/삭제)**")
        for name, pwd in list(st.session_state["users"].items()):
            col_a, col_b, col_c = st.columns([2, 2, 1])
            col_a.write(f"👤 **{name}**")
            col_b.write(f"비밀번호: `{pwd}`")
            if col_c.button("삭제", key=f"del_user_{name}"):
                try:
                    cell = ws_users.find(name, in_column=1)
                    if cell: ws_users.delete_rows(cell.row)
                except: pass
                st.session_state["data_loaded"] = False
                st.rerun()

    st.markdown("---")
    st.write("**일정 마감(블록) 관리**")
    tab_add, tab_del = st.tabs(["➕ 고정 및 레슨 일정 추가", "🗑️ 월별 일괄 삭제"])
    
    with tab_add:
        is_lesson = st.checkbox("✅ 레슨 일정 추가하기 (여러 날짜 개별 지정)")
        if is_lesson:
            st.info("💡 달력에서 날짜를 선택한 후 **[목록에 추가]** 버튼을 눌러 레슨일을 모아주세요.")
            col_d1, col_d2 = st.columns([3, 1])
            with col_d1:
                lesson_date = st.date_input("레슨 날짜 선택")
            with col_d2:
                st.write("") 
                if st.button("목록에 추가"):
                    if str(lesson_date) not in st.session_state["lesson_dates"]:
                        st.session_state["lesson_dates"].append(str(lesson_date))
                        st.rerun()
                    else:
                        st.warning("이미 추가된 날짜입니다.")
            
            if st.session_state["lesson_dates"]:
                st.write("📌 **현재 담긴 레슨 날짜:**")
                st.write(", ".join(sorted(st.session_state["lesson_dates"])))
                if st.button("담은 날짜 모두 비우기"):
                    st.session_state["lesson_dates"] = []
                    st.rerun()
        else:
            date_range = st.date_input("날짜 범위 지정 (시작일과 종료일 선택)", value=(datetime.date.today(), datetime.date.today()))
            
        st.markdown("---")
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            f_start = st.selectbox("시작 시간", all_time_slots)
        with col_t2:
            f_end_options = [t for t in all_time_slots_with_24 if t > f_start]
            f_end = st.selectbox("종료 시간", f_end_options)
            
        if st.button("지정된 시간 예약 막기", type="primary"):
            dates_to_process = []
            schedule_type = "레슨 일정" if is_lesson else "관리자 고정일정"
            
            if is_lesson:
                if not st.session_state["lesson_dates"]:
                    st.warning("선택된 레슨 날짜가 없습니다.")
                    st.stop()
                dates_to_process = [datetime.datetime.strptime(d, "%Y-%m-%d").date() for d in st.session_state["lesson_dates"]]
            else:
                if len(date_range) == 2: s_date, e_date = date_range
                else: s_date = e_date = date_range[0]
                curr_date = s_date
                while curr_date <= e_date:
                    dates_to_process.append(curr_date)
                    curr_date += datetime.timedelta(days=1)
                    
            added_count = 0
            for d in dates_to_process:
                is_overlap = any(r["date"] == str(d) and r["start_time"] < f_end and r["end_time"] > f_start for r in st.session_state["reservations"])
                if not is_overlap:
                    ws_res.append_row([str(uuid.uuid4()), str(d), f_start, f_end, schedule_type])
                    added_count += 1
            
            if added_count > 0:
                st.session_state["data_loaded"] = False
                st.success(f"성공적으로 {added_count}개의 {schedule_type}을(를) 마감 처리했습니다.")
                if is_lesson: st.session_state["lesson_dates"] = []
                st.rerun()
            else:
                st.warning("선택하신 시간대에 이미 다른 예약이 있어 일정을 추가하지 못했습니다.")
    
    with tab_del:
        fixed_res = [r for r in st.session_state["reservations"] if r["user_id"] in ["관리자 고정일정", "레슨 일정"]]
        if not fixed_res:
            st.write("현재 등록된 고정 및 레슨 일정이 없습니다.")
        else:
            fixed_months = sorted(list(set([r["date"][:7] for r in fixed_res])), reverse=True)
            del_month = st.selectbox("삭제할 일정의 월 선택", fixed_months)
            
            if st.button("해당 월 고정/레슨 일정 일괄 삭제"):
                st.session_state["reservations"] = [r for r in st.session_state["reservations"] if not (r["user_id"] in ["관리자 고정일정", "레슨 일정"] and r["date"].startswith(del_month))]
                rewrite_res_sheet() 
                st.session_state["data_loaded"] = False
                st.success(f"{del_month}월의 모든 고정 및 레슨 일정이 삭제되었습니다.")
                st.rerun()
            
    st.markdown("---")
    st.write("**전체 유저 예약 리스트 (월별 조회)**")
    if not st.session_state["reservations"]:
        st.write("현재 등록된 예약이 없습니다.")
    else:
        available_months = sorted(list(set([r["date"][:7] for r in st.session_state["reservations"]])), reverse=True)
        selected_month = st.selectbox("조회할 월을 선택하세요", available_months, key="view_month")
        filtered_res = [r for r in st.session_state["reservations"] if r["date"].startswith(selected_month)]
        filtered_res = sorted(filtered_res, key=lambda x: (x["date"], x["start_time"]))
        
        for r in filtered_res:
            col1, col2, col3, col4 = st.columns([1.5, 2, 2, 1])
            col1.write(f"{r['date']}")
            col2.write(f"{r['start_time']} ~ {r['end_time']}")
            col3.write(f"👤 {r['user_id']}")
            if col4.button("삭제", key=f"admin_del_{r['id']}"):
                try:
                    cell = ws_res.find(r["id"], in_column=1)
                    if cell: ws_res.delete_rows(cell.row)
                except: pass
                st.session_state["data_loaded"] = False
                st.rerun()

def main():
    if not st.session_state["logged_in"]: login_screen()
    else:
        col1, col2 = st.columns([4, 1])
        with col1: st.title("🥁프리모 드럼연습실 예약시스템")
        with col2:
            st.write("") 
            logout_button()
        st.markdown("---")
        if st.session_state["is_admin"]: admin_page()
        else: user_page()

if __name__ == "__main__":
    main()
