export function validateUser(req: any, res: any, next: any) {
    if (!req.body.name || !req.body.email) {
        return res.status(400).json({ error: 'Name and email are required' });
    }
    next();
}
