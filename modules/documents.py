import os
import uuid
import mimetypes
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash, send_from_directory, abort, current_app, jsonify
)
from werkzeug.utils import secure_filename
from database.db import get_db, fetchall, fetchone
from modules.logs import log_action
from modules.user_admin import has_permission

documents_bp = Blueprint('documents', __name__, url_prefix='/documents')

# Base storage directory for documents
UPLOAD_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads', 'documents')
os.makedirs(UPLOAD_ROOT, exist_ok=True)

ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'txt', 'csv', 'rtf', 'png', 'jpg', 'jpeg', 'gif', 'zip'
}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def format_file_size(size_bytes):
    if not size_bytes or size_bytes <= 0:
        return '0 B'
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}" if unit != 'B' else f"{int(size_bytes)} B"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def get_user_allowed_departments():
    """
    Returns None if Admin or Super Admin (can access all departments).
    Otherwise returns a list of departments accessible to the logged-in user.
    """
    role = session.get('role')
    if role in ('Admin', 'Super Admin'):
        return None

    user_dept = session.get('department')
    assigned = session.get('assigned_departments') or []

    allowed = []
    if user_dept:
        allowed.append(user_dept)
    for d in assigned:
        if d and d not in allowed:
            allowed.append(d)
    return allowed


def login_required(f):
    from functools import wraps

    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapped


@documents_bp.route('/')
@login_required
def index():
    if not has_permission('can_view', 'documents'):
        flash('You do not have permission to view Department Documents.', 'danger')
        return redirect(url_for('dashboard.index'))

    can_create = has_permission('can_create', 'documents')
    can_edit = has_permission('can_edit', 'documents')
    can_delete = has_permission('can_delete', 'documents')

    user_role = session.get('role')
    is_admin = user_role in ('Admin', 'Super Admin')
    allowed_depts = get_user_allowed_departments()

    search_query = request.args.get('search', '').strip()
    selected_dept = request.args.get('department', '').strip()
    selected_category = request.args.get('category', '').strip()

    conn = get_db()
    c = conn.cursor()

    # Fetch all active departments for dropdowns (cleaned of any whitespace)
    c.execute("SELECT name FROM departments ORDER BY name ASC")
    all_departments = sorted(list(set([r['name'].strip() for r in fetchall(c) if r['name'] and r['name'].strip()])))

    # Determine department filter condition
    params = []
    where_clauses = ["is_deleted = FALSE"]

    if not is_admin:
        # Non-admin user can only see their department's documents
        if not allowed_depts:
            where_clauses.append("1=0")  # User has no assigned department
        else:
            where_clauses.append("LOWER(department) = ANY(%s)")
            params.append([d.lower() for d in allowed_depts])
    else:
        # Admin can optionally filter by specific department
        if selected_dept:
            where_clauses.append("LOWER(department) = LOWER(%s)")
            params.append(selected_dept)

    if selected_category:
        where_clauses.append("LOWER(category) = LOWER(%s)")
        params.append(selected_category)

    if search_query:
        where_clauses.append("(title ILIKE %s OR description ILIKE %s OR original_filename ILIKE %s OR uploaded_by ILIKE %s)")
        search_pattern = f"%{search_query}%"
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern])

    where_sql = " AND ".join(where_clauses)
    query = f"""
        SELECT id, title, description, category, department,
               original_filename, stored_filename, file_size_bytes,
               file_type, uploaded_by, created_at
        FROM department_documents
        WHERE {where_sql}
        ORDER BY created_at DESC
    """
    c.execute(query, tuple(params))
    raw_documents = fetchall(c)

    # Format document file sizes and dates
    documents = []
    for doc in raw_documents:
        doc_dict = dict(doc)
        doc_dict['file_size_formatted'] = format_file_size(doc_dict.get('file_size_bytes', 0))
        doc_dict['ext'] = doc_dict['original_filename'].rsplit('.', 1)[-1].lower() if '.' in doc_dict['original_filename'] else ''
        documents.append(doc_dict)

    # Document stats
    total_docs = len(documents)
    total_size_bytes = sum(d.get('file_size_bytes', 0) for d in documents)
    total_size_formatted = format_file_size(total_size_bytes)

    # Distinct categories for filter
    categories = ['SOP & Policies', 'Safety Audit', 'Training & Induction', 'PPE Records', 'Inspection Report', 'Certificate', 'General']

    conn.close()

    # User's accessible upload departments and auto-selected default department
    user_upload_depts = all_departments if is_admin else allowed_depts
    user_dept = session.get('department') or (allowed_depts[0] if allowed_depts else '')
    
    # Calculate auto-selected department for upload
    if selected_dept:
        default_dept = selected_dept
    elif user_dept:
        default_dept = user_dept
    elif 'Administration' in all_departments:
        default_dept = 'Administration'
    elif all_departments:
        default_dept = all_departments[0]
    else:
        default_dept = 'Administration'

    return render_template(
        'documents.html',
        documents=documents,
        all_departments=all_departments,
        user_upload_depts=user_upload_depts,
        user_dept=user_dept,
        default_dept=default_dept,
        categories=categories,
        is_admin=is_admin,
        can_create=can_create,
        can_edit=can_edit,
        can_delete=can_delete,
        search_query=search_query,
        selected_dept=selected_dept,
        selected_category=selected_category,
        total_docs=total_docs,
        total_size_formatted=total_size_formatted
    )


@documents_bp.route('/upload', methods=['POST'])
@login_required
def upload():
    if not has_permission('can_create', 'documents'):
        flash('You do not have permission to upload documents.', 'danger')
        return redirect(url_for('documents.index'))

    user_role = session.get('role')
    is_admin = user_role in ('Admin', 'Super Admin')
    allowed_depts = get_user_allowed_departments()

    title = request.form.get('title', '').strip()
    category = request.form.get('category', 'General').strip() or 'General'
    description = request.form.get('description', '').strip()

    # Department handling:
    # Admin selects from dropdown; non-admin gets automatic department from login credentials
    if is_admin:
        dept = request.form.get('department', '').strip()
        if not dept:
            flash('Please select a department for the document.', 'danger')
            return redirect(url_for('documents.index'))
    else:
        dept = session.get('department')
        if not dept and allowed_depts:
            dept = allowed_depts[0]
        if not dept:
            flash('No department assigned to your login credentials.', 'danger')
            return redirect(url_for('documents.index'))

    if 'document' not in request.files:
        flash('No file selected.', 'danger')
        return redirect(url_for('documents.index'))

    file = request.files['document']
    if not file or file.filename == '':
        flash('Please select a file to upload.', 'danger')
        return redirect(url_for('documents.index'))

    if not title:
        title = os.path.splitext(file.filename)[0]

    original_filename = secure_filename(file.filename)
    if not original_filename:
        original_filename = f"document_{uuid.uuid4().hex[:8]}"

    if not allowed_file(file.filename):
        flash('Unsupported file type. Allowed: PDF, Word, Excel, PowerPoint, Text, Images, Zip.', 'danger')
        return redirect(url_for('documents.index'))

    # Generate unique stored filename
    ext = os.path.splitext(original_filename)[1].lower()
    unique_stored_name = f"{uuid.uuid4().hex}_{original_filename}"
    dept_folder = secure_filename(dept.lower().replace(' ', '_'))
    target_dir = os.path.join(UPLOAD_ROOT, dept_folder)
    os.makedirs(target_dir, exist_ok=True)

    target_path = os.path.join(target_dir, unique_stored_name)
    file.save(target_path)

    file_size_bytes = os.path.getsize(target_path)
    file_type = mimetypes.guess_type(original_filename)[0] or 'application/octet-stream'

    username = session.get('user', 'unknown')
    full_name = session.get('full_name') or username

    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO department_documents (
            title, description, category, department,
            original_filename, stored_filename, file_path,
            file_size_bytes, file_type, uploaded_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        title, description, category, dept,
        original_filename, unique_stored_name, target_path,
        file_size_bytes, file_type, f"{full_name} ({username})"
    ))
    new_doc_id = c.fetchone()[0]
    conn.commit()
    conn.close()

    log_action(
        'upload_document',
        'documents',
        new_doc_id,
        f"Uploaded document '{title}' ({original_filename}) for department '{dept}'",
        department=dept
    )

    flash(f"Document '{title}' uploaded successfully for {dept}!", 'success')
    return redirect(url_for('documents.index'))


@documents_bp.route('/view/<int:doc_id>')
@login_required
def view_document(doc_id):
    is_admin = session.get('role') in ('Admin', 'Super Admin')
    allowed_depts = get_user_allowed_departments()

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM department_documents WHERE id = %s AND is_deleted = FALSE", (doc_id,))
    doc = fetchone(c)
    conn.close()

    if not doc:
        flash('Document not found or has been deleted.', 'danger')
        return redirect(url_for('documents.index'))

    # Security check: department scope
    if not is_admin:
        if not allowed_depts or doc['department'].lower() not in [d.lower() for d in allowed_depts]:
            flash('Access denied. You cannot view documents from other departments.', 'danger')
            return redirect(url_for('documents.index'))

    file_dir = os.path.dirname(doc['file_path'])
    filename = os.path.basename(doc['file_path'])

    if not os.path.exists(doc['file_path']):
        flash('File not found on storage server.', 'danger')
        return redirect(url_for('documents.index'))

    return send_from_directory(
        file_dir,
        filename,
        as_attachment=False,
        download_name=doc['original_filename'],
        mimetype=doc.get('file_type')
    )


@documents_bp.route('/download/<int:doc_id>')
@login_required
def download_document(doc_id):
    is_admin = session.get('role') in ('Admin', 'Super Admin')
    allowed_depts = get_user_allowed_departments()

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM department_documents WHERE id = %s AND is_deleted = FALSE", (doc_id,))
    doc = fetchone(c)
    conn.close()

    if not doc:
        flash('Document not found or has been deleted.', 'danger')
        return redirect(url_for('documents.index'))

    # Security check: department scope
    if not is_admin:
        if not allowed_depts or doc['department'].lower() not in [d.lower() for d in allowed_depts]:
            flash('Access denied. You cannot download documents from other departments.', 'danger')
            return redirect(url_for('documents.index'))

    file_dir = os.path.dirname(doc['file_path'])
    filename = os.path.basename(doc['file_path'])

    if not os.path.exists(doc['file_path']):
        flash('File not found on storage server.', 'danger')
        return redirect(url_for('documents.index'))

    log_action(
        'download_document',
        'documents',
        doc_id,
        f"Downloaded document '{doc['title']}' ({doc['original_filename']})",
        department=doc['department']
    )

    return send_from_directory(
        file_dir,
        filename,
        as_attachment=True,
        download_name=doc['original_filename']
    )


@documents_bp.route('/delete/<int:doc_id>', methods=['POST'])
@login_required
def delete_document(doc_id):
    if not has_permission('can_delete', 'documents'):
        flash('You do not have permission to delete documents.', 'danger')
        return redirect(url_for('documents.index'))

    is_admin = session.get('role') in ('Admin', 'Super Admin')
    allowed_depts = get_user_allowed_departments()

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM department_documents WHERE id = %s AND is_deleted = FALSE", (doc_id,))
    doc = fetchone(c)

    if not doc:
        conn.close()
        flash('Document not found.', 'danger')
        return redirect(url_for('documents.index'))

    # Security check: only Admin or user in that department
    if not is_admin:
        if not allowed_depts or doc['department'].lower() not in [d.lower() for d in allowed_depts]:
            conn.close()
            flash('Permission denied. You cannot delete documents from other departments.', 'danger')
            return redirect(url_for('documents.index'))

    # Soft delete in database
    c.execute("UPDATE department_documents SET is_deleted = TRUE, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (doc_id,))
    conn.commit()
    conn.close()

    log_action(
        'delete_document',
        'documents',
        doc_id,
        f"Deleted document '{doc['title']}' ({doc['original_filename']})",
        department=doc['department']
    )

    flash(f"Document '{doc['title']}' removed successfully.", 'success')
    return redirect(url_for('documents.index'))


@documents_bp.route('/edit/<int:doc_id>', methods=['POST'])
@login_required
def edit_document(doc_id):
    if not has_permission('can_edit', 'documents'):
        flash('You do not have permission to edit documents.', 'danger')
        return redirect(url_for('documents.index'))

    is_admin = session.get('role') in ('Admin', 'Super Admin')
    allowed_depts = get_user_allowed_departments()

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM department_documents WHERE id = %s AND is_deleted = FALSE", (doc_id,))
    doc = fetchone(c)

    if not doc:
        conn.close()
        flash('Document not found.', 'danger')
        return redirect(url_for('documents.index'))

    # Security check: only Admin or user in that department
    if not is_admin:
        if not allowed_depts or doc['department'].lower() not in [d.lower() for d in allowed_depts]:
            conn.close()
            flash('Permission denied. You cannot edit documents from other departments.', 'danger')
            return redirect(url_for('documents.index'))

    title = request.form.get('title', '').strip()
    category = request.form.get('category', 'General').strip() or 'General'
    description = request.form.get('description', '').strip()

    if not title:
        title = doc['title']

    if is_admin:
        dept = request.form.get('department', '').strip() or doc['department']
    else:
        dept = doc['department']

    # Check if a replacement file was uploaded
    if 'document' in request.files and request.files['document'].filename != '':
        file = request.files['document']
        if allowed_file(file.filename):
            original_filename = secure_filename(file.filename) or f"document_{uuid.uuid4().hex[:8]}"
            unique_stored_name = f"{uuid.uuid4().hex}_{original_filename}"
            dept_folder = secure_filename(dept.lower().replace(' ', '_'))
            target_dir = os.path.join(UPLOAD_ROOT, dept_folder)
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, unique_stored_name)
            file.save(target_path)
            file_size_bytes = os.path.getsize(target_path)
            file_type = mimetypes.guess_type(original_filename)[0] or 'application/octet-stream'

            c.execute("""
                UPDATE department_documents
                SET title = %s, category = %s, description = %s, department = %s,
                    original_filename = %s, stored_filename = %s, file_path = %s,
                    file_size_bytes = %s, file_type = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (title, category, description, dept, original_filename, unique_stored_name, target_path, file_size_bytes, file_type, doc_id))
        else:
            flash('Invalid file type uploaded. Other details updated.', 'warning')
            c.execute("""
                UPDATE department_documents
                SET title = %s, category = %s, description = %s, department = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (title, category, description, dept, doc_id))
    else:
        c.execute("""
            UPDATE department_documents
            SET title = %s, category = %s, description = %s, department = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (title, category, description, dept, doc_id))

    conn.commit()
    conn.close()

    log_action(
        'edit_document',
        'documents',
        doc_id,
        f"Updated document '{title}' (Department: {dept})",
        department=dept
    )

    flash(f"Document '{title}' updated successfully.", 'success')
    return redirect(url_for('documents.index'))


@documents_bp.route('/bulk_delete', methods=['POST'])
@login_required
def bulk_delete():
    if not has_permission('can_delete', 'documents'):
        return jsonify({'success': False, 'message': 'You do not have permission to delete documents.'}), 403

    data = request.get_json(silent=True) or request.form
    raw_ids = data.get('doc_ids') or []
    if isinstance(raw_ids, str):
        try:
            import json
            doc_ids = json.loads(raw_ids)
        except Exception:
            doc_ids = [int(x) for x in raw_ids.split(',') if x.strip().isdigit()]
    else:
        doc_ids = [int(x) for x in raw_ids if str(x).isdigit()]

    if not doc_ids:
        return jsonify({'success': False, 'message': 'No documents selected.'}), 400

    is_admin = session.get('role') in ('Admin', 'Super Admin')
    allowed_depts = get_user_allowed_departments()

    conn = get_db()
    c = conn.cursor()

    if not is_admin:
        if not allowed_depts:
            conn.close()
            return jsonify({'success': False, 'message': 'Permission denied.'}), 403
        c.execute("""
            SELECT id FROM department_documents
            WHERE id = ANY(%s) AND LOWER(department) = ANY(%s) AND is_deleted = FALSE
        """, (doc_ids, [d.lower() for d in allowed_depts]))
        valid_ids = [r['id'] for r in fetchall(c)]
    else:
        valid_ids = doc_ids

    if not valid_ids:
        conn.close()
        return jsonify({'success': False, 'message': 'No valid documents to delete.'}), 400

    c.execute("""
        UPDATE department_documents
        SET is_deleted = TRUE, updated_at = CURRENT_TIMESTAMP
        WHERE id = ANY(%s)
    """, (valid_ids,))
    deleted_count = c.rowcount
    conn.commit()
    conn.close()

    log_action('bulk_delete_documents', 'documents', None, f"Bulk deleted {deleted_count} documents")
    flash(f"{deleted_count} documents deleted successfully.", 'success')
    return jsonify({'success': True, 'count': deleted_count, 'message': f'{deleted_count} documents deleted successfully.'})


@documents_bp.route('/bulk_edit', methods=['POST'])
@login_required
def bulk_edit():
    if not has_permission('can_edit', 'documents'):
        return jsonify({'success': False, 'message': 'You do not have permission to edit documents.'}), 403

    data = request.get_json(silent=True) or request.form
    raw_ids = data.get('doc_ids') or []
    if isinstance(raw_ids, str):
        try:
            import json
            doc_ids = json.loads(raw_ids)
        except Exception:
            doc_ids = [int(x) for x in raw_ids.split(',') if x.strip().isdigit()]
    else:
        doc_ids = [int(x) for x in raw_ids if str(x).isdigit()]

    if not doc_ids:
        return jsonify({'success': False, 'message': 'No documents selected.'}), 400

    is_admin = session.get('role') in ('Admin', 'Super Admin')
    allowed_depts = get_user_allowed_departments()

    category = (data.get('category') or '').strip()
    department = (data.get('department') or '').strip() if is_admin else None
    description = (data.get('description') or '').strip()
    update_category = data.get('update_category') in (True, 'true', '1', 'on')
    update_department = data.get('update_department') in (True, 'true', '1', 'on') if is_admin else False
    update_description = data.get('update_description') in (True, 'true', '1', 'on')

    set_clauses = ["updated_at = CURRENT_TIMESTAMP"]
    params = []

    if update_category and category:
        set_clauses.append("category = %s")
        params.append(category)

    if update_department and department:
        set_clauses.append("department = %s")
        params.append(department)

    if update_description:
        set_clauses.append("description = %s")
        params.append(description)

    if len(set_clauses) == 1:
        return jsonify({'success': False, 'message': 'Please select at least one field to update.'}), 400

    conn = get_db()
    c = conn.cursor()

    if not is_admin:
        if not allowed_depts:
            conn.close()
            return jsonify({'success': False, 'message': 'Permission denied.'}), 403
        c.execute("""
            SELECT id FROM department_documents
            WHERE id = ANY(%s) AND LOWER(department) = ANY(%s) AND is_deleted = FALSE
        """, (doc_ids, [d.lower() for d in allowed_depts]))
        valid_ids = [r['id'] for r in fetchall(c)]
    else:
        valid_ids = doc_ids

    if not valid_ids:
        conn.close()
        return jsonify({'success': False, 'message': 'No valid documents to update.'}), 400

    query = f"""
        UPDATE department_documents
        SET {", ".join(set_clauses)}
        WHERE id = ANY(%s)
    """
    params.append(valid_ids)
    c.execute(query, tuple(params))
    updated_count = c.rowcount
    conn.commit()
    conn.close()

    log_action('bulk_edit_documents', 'documents', None, f"Bulk updated {updated_count} documents")
    flash(f"{updated_count} documents updated successfully.", 'success')
    return jsonify({'success': True, 'count': updated_count, 'message': f'{updated_count} documents updated successfully.'})
